# CryptomatteExtractor

Use **Unreal Engine Cryptomatte renders in Photoshop or Affinity Photo.**

Photoshop and Affinity cannot read multilayer EXRs or decode Cryptomatte, so the
per object selection data that Unreal writes is normally unreachable in a 2D
editor. This tool reads the EXR, decodes the Cryptomatte, and writes out flat
files you can open and select from directly.

It produces three kinds of output (you choose which):

1. **Passes / AOVs.** Each channel group becomes its own EXR: beauty (RGBA),
   Z depth, normals (XYZ mapped to RGB), and any other pass present (diffuse,
   specular, ambient occlusion, etc.). Single channel passes such as Z depth are
   written as grayscale so they display correctly.
2. **Colored Object ID pass (recommended).** A single RGB image where every object
   gets a clearly distinct color, similar to the Corona ID render or the Nuke
   Cryptomatte preview. With one file you can isolate any object in Photoshop or
   Affinity using the magic wand / "Select by color".
3. **Individual Cryptomatte mattes.** One grayscale matte (0 to 1) per object or
   material listed in the EXR manifest. Use these when you need an exact alpha edge
   for a specific object.

Everything is written as float EXR, so the full range (HDR, real depth values) is
preserved.

## Why

A Cryptomatte EXR stores object identity as paired id/coverage channels plus a JSON
manifest in the header. 2D editors ignore all of that. CryptomatteExtractor decodes
it the standard way (it sums coverage across ranks whose id matches each object) and
turns it into images a compositor can actually use.

## Screenshots

The colored Object ID pass looks like a flat shaded version of your scene where each
mesh is a solid color. One magic wand click selects a whole object.

_(Add your own screenshots here.)_

## Requirements

- Python 3.9 to 3.13 (64 bit). **OpenEXR has no wheels for Python 3.14+ yet**, so
  use 3.13 or lower.
- `numpy`, `OpenEXR`, and `PySide6` (only needed for the GUI).

Install the dependencies:

```
pip install -r requirements.txt
```

## Run from source

GUI (also accepts drag and drop of .exr files):

```
python crypto_extractor.py
```

Command line:

```
python crypto_extractor.py input.exr -o output_folder
python crypto_extractor.py input.exr --object-ids        # colored id pass
python crypto_extractor.py input.exr --no-crypto         # skip per object mattes
python crypto_extractor.py input.exr --no-passes         # only cryptomatte output
```

## Build a standalone .exe (Windows)

You do not need Python to *run* the built executable, only to build it.

1. Put `crypto_extractor.py`, `requirements.txt` and `build.bat` in one folder.
2. Double click `build.bat`. It creates an isolated environment with Python 3.13,
   installs the dependencies, and runs PyInstaller.
3. The result is `dist\CryptomatteExtractor.exe`. It is self contained: copy it
   anywhere and run it with a double click.

You can also build manually:

```
pip install pyinstaller
pyinstaller --onefile --windowed --name CryptomatteExtractor crypto_extractor.py
```

Notes on the executable: it runs on Windows 10 or newer (64 bit). Because it is a
onefile build it takes a few seconds to start the first time. Unsigned PyInstaller
executables may trigger a SmartScreen warning; that is the lack of a code signing
certificate, not a problem with the program.

## Unreal Engine setup

To get a Cryptomatte EXR out of Unreal:

1. Use the **Movie Render Queue**.
2. Add a **Deferred Rendering** pass and enable **Cryptomatte** (Object, Material,
   or Asset, depending on what you want to select by).
3. Set the output format to **EXR** (multilayer, float).
4. Render, then drop the resulting `.exr` into CryptomatteExtractor.

## Recommended Affinity / Photoshop workflow

1. Export the **colored Object ID pass**.
2. Open it as a layer above your beauty render.
3. With the ID layer active, use the **magic wand** (in Affinity: Flood Select /
   Selection, with a low tolerance and "Contiguous" off). One click selects every
   pixel of that color, i.e. that whole object.
4. Switch back to the beauty layer with the selection active and adjust, mask, or
   cut out just that element.

For a perfectly antialiased edge on a single object, also export its individual
matte and use it as a layer mask.

## How the decoding works

- Cryptomatte metadata is read from the EXR header
  (`cryptomatte/<hash>/manifest`) using the modern OpenEXR API, which preserves
  those custom attributes.
- For each object, coverage is summed across all ranks whose id bit pattern matches
  the object id from the manifest (exact 32 bit comparison, no float tolerance).
- The Object ID pass assigns each object a stable color spaced by the golden ratio
  on the hue wheel, taking the dominant id (rank 0) per pixel.

## License

MIT. See [LICENSE](LICENSE).
