#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptomatteExtractor
====================

Split the layers of an .exr render into separate files, ready to open in
Photoshop or Affinity Photo. Built for Unreal Engine Movie Render Queue
Cryptomatte output, but works with any standard Cryptomatte EXR.

It can export:

  1. Passes / AOVs       -> each channel group (beauty, Z depth, normals,
                            diffuse, specular...) as its own EXR.
  2. Object ID pass      -> a single RGB image where every object gets a clearly
                            distinct color (Corona / Nuke preview style). Perfect
                            for "Select by color" in Photoshop or Affinity.
  3. Cryptomatte mattes  -> one grayscale matte (0..1) per object/material in the
                            manifest. Use when you need an exact alpha.

Everything is written as float EXR (full range preserved).

Usage:
    GUI:   python crypto_extractor.py
           (you can also drag and drop .exr files onto the window)
    CLI:   python crypto_extractor.py input.exr -o output_folder

Dependencies: OpenEXR (>=3.2), numpy  (PySide6 only for the GUI).
"""

import os
import sys
import json
import struct
import colorsys
import argparse

import numpy as np
import OpenEXR


# --------------------------------------------------------------------------- #
#  Cryptomatte helpers
# --------------------------------------------------------------------------- #

def hex_to_uint(hex_str):
    """Hex bits of an id -> uint32."""
    return int(hex_str, 16) & 0xFFFFFFFF


def _as_str(val):
    if isinstance(val, bytes):
        return val.decode("utf-8", "replace")
    return str(val)


def find_cryptomatte_layers(header):
    """
    Return { typename: {"name": str, "manifest": {name: id_uint32}} }.
    Header keys look like 'cryptomatte/<hash>/name', '.../manifest'.
    """
    cryptos = {}
    for key, val in header.items():
        if not str(key).startswith("cryptomatte/"):
            continue
        parts = str(key).split("/")
        if len(parts) < 3:
            continue
        hash_id, attr = parts[1], parts[2]
        cryptos.setdefault(hash_id, {})[attr] = _as_str(val)

    result = {}
    for hash_id, attrs in cryptos.items():
        name = attrs.get("name")
        if not name:
            continue
        manifest = {}
        raw = attrs.get("manifest")
        if raw:
            try:
                manifest = {n: hex_to_uint(h) for n, h in json.loads(raw).items()}
            except Exception:
                manifest = {}
        result[name] = {"name": name, "manifest": manifest, "hash_id": hash_id}
    return result


# --------------------------------------------------------------------------- #
#  EXR reading (modern OpenEXR.File API: keeps cryptomatte attributes)
# --------------------------------------------------------------------------- #

def read_exr(path):
    """Return (header, channels_dict, width, height)."""
    f = OpenEXR.File(path, separate_channels=True)
    part = f.parts[0]
    header = dict(part.header)
    channels = {}
    height = width = 0
    for cname, chan in part.channels.items():
        arr = np.asarray(chan.pixels)
        if arr.ndim == 3:
            arr = arr[..., 0]
        arr = arr.astype(np.float32, copy=False)
        height, width = arr.shape
        channels[cname] = arr
    return header, channels, width, height


# --------------------------------------------------------------------------- #
#  Pass / AOV grouping
# --------------------------------------------------------------------------- #

def group_passes(channel_names, crypto_names):
    crypto_prefixes = tuple(crypto_names)
    beauty = {"R", "G", "B", "A"}
    groups = {}
    for cn in channel_names:
        base = cn.split(".")[0]
        if any(base == cp or (base.startswith(cp) and base[len(cp):].isdigit())
               for cp in crypto_prefixes):
            continue
        if "." in cn:
            layer = cn.rsplit(".", 1)[0]
        elif cn in beauty:
            layer = "beauty"
        else:
            layer = cn
        groups.setdefault(layer, []).append(cn)
    return groups


# --------------------------------------------------------------------------- #
#  EXR writing
# --------------------------------------------------------------------------- #

def write_exr(path, channels, width, height):
    chan_objs = {name: OpenEXR.Channel(name, arr.astype(np.float32, copy=False))
                 for name, arr in channels.items()}
    OpenEXR.File({}, chan_objs).write(path)


def _suffix(sub):
    m = {"r": "R", "g": "G", "b": "B", "a": "A",
         "x": "R", "y": "G", "z": "B", "w": "A"}
    return m.get(sub.lower(), sub)


# --------------------------------------------------------------------------- #
#  Cryptomatte: levels, mattes and object id pass
# --------------------------------------------------------------------------- #

def _level_channels(channels, prefix):
    """Return [id0, cov0, id1, cov1] for a level, or None."""
    for combo in ((".R", ".G", ".B", ".A"), (".r", ".g", ".b", ".a")):
        keys = [prefix + s for s in combo]
        if keys[0] in channels and keys[1] in channels:
            res = [channels[keys[0]], channels[keys[1]]]
            if keys[2] in channels and keys[3] in channels:
                res += [channels[keys[2]], channels[keys[3]]]
            return res
    return None


def _iter_levels(channels, crypto_name):
    """Yield (id_arr, cov_arr) for every rank of the cryptomatte."""
    level = 0
    while level <= 32:
        chans = _level_channels(channels, "%s%02d" % (crypto_name, level))
        if chans is None:
            break
        yield chans[0], chans[1]
        if len(chans) >= 4:
            yield chans[2], chans[3]
        level += 1


def extract_crypto_matte(channels, crypto_name, target_uint, width, height):
    """Matte 0..1: sum of coverage over ranks whose id bits == target."""
    matte = np.zeros((height, width), dtype=np.float32)
    for id_arr, cov_arr in _iter_levels(channels, crypto_name):
        mask = id_arr.view(np.uint32) == np.uint32(target_uint)
        matte += np.where(mask, cov_arr, 0.0)
    return np.clip(matte, 0.0, 1.0)


def _id_color(uint_id, index):
    """Stable, well separated RGB color for an id.
    Hue is spaced by the golden ratio; saturation/value get a small nudge."""
    hue = (index * 0.6180339887498949) % 1.0
    sat = 0.55 + 0.20 * ((uint_id >> 8) & 0xFF) / 255.0
    val = 0.80 + 0.18 * ((uint_id >> 16) & 0xFF) / 255.0
    return colorsys.hsv_to_rgb(hue, min(sat, 1.0), min(val, 1.0))


def build_objectid_pass(channels, crypto_name, manifest, width, height):
    """
    Return a {R,G,B} dict painting each manifest object with a distinct color.
    Each pixel takes its dominant id (rank 0). Background stays black.
    """
    chans0 = _level_channels(channels, "%s00" % crypto_name)
    if chans0 is None:
        return None
    id0 = chans0[0].view(np.uint32)

    R = np.zeros((height, width), np.float32)
    G = np.zeros((height, width), np.float32)
    B = np.zeros((height, width), np.float32)

    for idx, (name, uint_id) in enumerate(sorted(manifest.items())):
        mask = id0 == np.uint32(uint_id)
        if not mask.any():
            continue
        r, g, b = _id_color(uint_id, idx)
        R[mask] = r
        G[mask] = g
        B[mask] = b
    return {"R": R, "G": G, "B": B}


# --------------------------------------------------------------------------- #
#  Orchestration
# --------------------------------------------------------------------------- #

def safe_name(s):
    keep = "-_.() "
    return "".join(c if c.isalnum() or c in keep else "_" for c in s).strip()


def process(path, out_dir, do_passes=True, do_crypto=True, do_objectid=False,
            progress=None):
    """Process one EXR and write the results. Return list of created paths."""
    header, channels, width, height = read_exr(path)
    cryptos = find_cryptomatte_layers(header)
    base = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    created = []

    def report(msg):
        if progress:
            progress(msg)

    # --- Passes / AOVs ---
    if do_passes:
        groups = group_passes(channels.keys(), cryptos.keys())
        for layer, chan_list in sorted(groups.items()):
            if len(chan_list) == 1:
                arr = channels[chan_list[0]]
                out_channels = {"R": arr, "G": arr, "B": arr}
            else:
                out_channels = {}
                for cn in chan_list:
                    sub = cn.rsplit(".", 1)[1] if "." in cn else cn
                    out_channels[_suffix(sub)] = channels[cn]
            out_path = os.path.join(out_dir, "%s__%s.exr" % (base, safe_name(layer)))
            write_exr(out_path, out_channels, width, height)
            created.append(out_path)
            report("Pass exported: %s" % os.path.basename(out_path))

    # --- Object ID pass (one file per cryptomatte) ---
    if do_objectid:
        for cname, info in cryptos.items():
            manifest = info["manifest"]
            if not manifest:
                report("Cryptomatte '%s' has no manifest, skipped (object id)." % cname)
                continue
            idpass = build_objectid_pass(channels, cname, manifest, width, height)
            if idpass is None:
                continue
            fn = "%s__%s__ObjectIDs.exr" % (base, safe_name(cname))
            out_path = os.path.join(out_dir, fn)
            write_exr(out_path, idpass, width, height)
            created.append(out_path)
            report("Object ID pass exported: %s" % os.path.basename(out_path))

    # --- Individual Cryptomatte mattes ---
    if do_crypto:
        for cname, info in cryptos.items():
            manifest = info["manifest"]
            if not manifest:
                report("Cryptomatte '%s' has no manifest, skipped." % cname)
                continue
            for obj_name, uint_id in manifest.items():
                matte = extract_crypto_matte(channels, cname, uint_id, width, height)
                if matte.max() == 0:
                    continue
                out_channels = {"R": matte, "G": matte, "B": matte}
                fn = "%s__%s__%s.exr" % (base, safe_name(cname), safe_name(obj_name))
                out_path = os.path.join(out_dir, fn)
                write_exr(out_path, out_channels, width, height)
                created.append(out_path)
                report("Matte exported: %s" % os.path.basename(out_path))

    return created


# --------------------------------------------------------------------------- #
#  GUI (PySide6)
# --------------------------------------------------------------------------- #

def run_gui():
    from PySide6 import QtWidgets, QtCore

    class Worker(QtCore.QThread):
        msg = QtCore.Signal(str)
        done = QtCore.Signal(list)
        fail = QtCore.Signal(str)

        def __init__(self, files, out_dir, passes, crypto, objectid):
            super().__init__()
            self.files, self.out_dir = files, out_dir
            self.passes, self.crypto, self.objectid = passes, crypto, objectid

        def run(self):
            try:
                all_created = []
                for f in self.files:
                    self.msg.emit("Processing %s ..." % os.path.basename(f))
                    all_created += process(
                        f, self.out_dir, self.passes, self.crypto, self.objectid,
                        progress=self.msg.emit)
                self.done.emit(all_created)
            except Exception as e:
                self.fail.emit(str(e))

    class DropList(QtWidgets.QListWidget):
        """List widget that accepts dropped .exr files."""
        filesDropped = QtCore.Signal(list)

        def __init__(self):
            super().__init__()
            self.setAcceptDrops(True)
            self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        def dragEnterEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dragMoveEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dropEvent(self, e):
            paths = [u.toLocalFile() for u in e.mimeData().urls()
                     if u.toLocalFile().lower().endswith(".exr")]
            if paths:
                self.filesDropped.emit(paths)
                e.acceptProposedAction()

    class Win(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Cryptomatte / EXR Layer Extractor")
            self.resize(680, 540)
            self.files = []
            self.out_dir = ""
            self.setAcceptDrops(True)

            v = QtWidgets.QVBoxLayout(self)

            tip = QtWidgets.QLabel("Drag your .exr files here  (or use the button)")
            tip.setStyleSheet("color:#9aa0a6; font-style:italic;")

            self.list = DropList()
            self.list.setMinimumHeight(110)
            self.list.filesDropped.connect(self.add_files)

            btn_files = QtWidgets.QPushButton("Choose .exr files")
            btn_files.clicked.connect(self.pick_files)
            btn_clear = QtWidgets.QPushButton("Clear list")
            btn_clear.clicked.connect(self.clear_files)
            hb = QtWidgets.QHBoxLayout()
            hb.addWidget(btn_files)
            hb.addWidget(btn_clear)

            self.lbl_out = QtWidgets.QLabel("Output folder: (next to the source file)")
            btn_out = QtWidgets.QPushButton("Choose output folder")
            btn_out.clicked.connect(self.pick_out)

            self.chk_passes = QtWidgets.QCheckBox("Export passes / AOVs (Z depth, normals, etc.)")
            self.chk_passes.setChecked(True)
            self.chk_objid = QtWidgets.QCheckBox("Export colored Object ID pass (recommended)")
            self.chk_objid.setChecked(True)
            self.chk_crypto = QtWidgets.QCheckBox("Export one matte per object (many files)")
            self.chk_crypto.setChecked(False)

            self.btn_run = QtWidgets.QPushButton("Extract layers")
            self.btn_run.clicked.connect(self.run_extract)

            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)

            v.addWidget(tip)
            v.addWidget(self.list)
            v.addLayout(hb)
            v.addWidget(self.lbl_out)
            v.addWidget(btn_out)
            v.addWidget(self.chk_passes)
            v.addWidget(self.chk_objid)
            v.addWidget(self.chk_crypto)
            v.addWidget(self.btn_run)
            v.addWidget(QtWidgets.QLabel("Log:"))
            v.addWidget(self.log)

        # dropping anywhere on the window works too
        def dragEnterEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dropEvent(self, e):
            paths = [u.toLocalFile() for u in e.mimeData().urls()
                     if u.toLocalFile().lower().endswith(".exr")]
            self.add_files(paths)

        def add_files(self, paths):
            for p in paths:
                if p and p not in self.files:
                    self.files.append(p)
                    self.list.addItem(os.path.basename(p))

        def clear_files(self):
            self.files = []
            self.list.clear()

        def pick_files(self):
            files, _ = QtWidgets.QFileDialog.getOpenFileNames(
                self, "Select EXR files", "", "EXR (*.exr)")
            self.add_files(files)

        def pick_out(self):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Output folder")
            if d:
                self.out_dir = d
                self.lbl_out.setText("Output folder: %s" % d)

        def run_extract(self):
            if not self.files:
                QtWidgets.QMessageBox.warning(self, "Notice",
                                              "Add at least one .exr file")
                return
            out = self.out_dir or os.path.dirname(self.files[0])
            self.log.clear()
            self.btn_run.setEnabled(False)
            self.worker = Worker(self.files, out,
                                 self.chk_passes.isChecked(),
                                 self.chk_crypto.isChecked(),
                                 self.chk_objid.isChecked())
            self.worker.msg.connect(lambda m: self.log.appendPlainText(m))
            self.worker.done.connect(self.on_done)
            self.worker.fail.connect(self.on_fail)
            self.worker.start()

        def on_done(self, created):
            self.btn_run.setEnabled(True)
            self.log.appendPlainText("\nDone. %d file(s) created." % len(created))
            QtWidgets.QMessageBox.information(
                self, "Finished", "%d EXR files created." % len(created))

        def on_fail(self, err):
            self.btn_run.setEnabled(True)
            self.log.appendPlainText("\nERROR: " + err)
            QtWidgets.QMessageBox.critical(self, "Error", err)

    app = QtWidgets.QApplication(sys.argv)
    win = Win()
    win.show()
    sys.exit(app.exec())


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Split EXR layers into individual EXR files.")
    ap.add_argument("input", nargs="?", help="input .exr file")
    ap.add_argument("-o", "--output", help="output folder")
    ap.add_argument("--no-passes", action="store_true", help="do not export passes/AOVs")
    ap.add_argument("--no-crypto", action="store_true", help="do not export per object mattes")
    ap.add_argument("--object-ids", action="store_true", help="export colored object id pass")
    args = ap.parse_args()

    if not args.input:
        run_gui()
        return

    out_dir = args.output or os.path.dirname(os.path.abspath(args.input)) or "."
    created = process(args.input, out_dir,
                      do_passes=not args.no_passes,
                      do_crypto=not args.no_crypto,
                      do_objectid=args.object_ids,
                      progress=print)
    print("\nDone. %d file(s) created in %s" % (len(created), out_dir))


if __name__ == "__main__":
    main()
