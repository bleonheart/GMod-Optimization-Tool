<p align="center">
 <strong>Garry's Mod Optimization Tool</strong><br/>
 A desktop utility for cleaning, compressing, and reorganizing Garry's Mod addons, maps, and content packs.<br/>
 Built to help server owners and content maintainers cut down file size, remove dead weight, and streamline deployment workflows.<br/><br/>
 <img src="https://raw.githubusercontent.com/bleonheart/Garry-s-Mod-Optimization-Tool/main/icon.png" alt="Garry's Mod Optimization Tool Logo" width="160" />
</p>

<p align="center">
 <a href="https://github.com/bleonheart/Garry-s-Mod-Optimization-Tool/stargazers">
  <img src="https://img.shields.io/github/stars/bleonheart/Garry-s-Mod-Optimization-Tool?style=social" alt="GitHub Stars" />
 </a>
 <a href="https://www.gnu.org/licenses/gpl-3.0">
  <img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License GPL v3" />
 </a>
</p>

<h1 align="center">Garry's Mod Optimization Tool</h1>

---

## Quick Start

<p align="center">
 Clone the repository, run <code>run.bat</code>, and let the tool set itself up automatically on Windows.
</p>

```bash
git clone https://github.com/bleonheart/Garry-s-Mod-Optimization-Tool.git
cd Garry-s-Mod-Optimization-Tool
run.bat
```

The batch launcher will:

1. Pull the latest changes
2. Create a local virtual environment if needed
3. Install Python dependencies
4. Launch the desktop application

## Usage

Run the launcher without arguments:

```bash
run.bat
```

This mode will:

1. Pull the latest changes from the repository
2. Create the `venv` virtual environment if it does not already exist
3. Activate the virtual environment
4. Install or update dependencies from `requirements.txt`
5. Start the desktop app with `python -m app.main`

## Features

### Textures Compression

- `Clamp VTF file sizes`  
  Resize oversized `.vtf` textures to a chosen maximum resolution to reduce addon size while keeping practical visual quality.

- `Use DXT for VTFs`  
  Recompress `.vtf` textures with DXT formats for significantly smaller texture files with minimal visible loss in most cases.

- `Remove mipmaps`  
  Strip mipmaps from textures when you want to save space on assets that do not benefit from distance-based texture levels.

- `Clamp PNG file sizes`  
  Resize large `.png` assets such as UI graphics, icons, and overlays so they take up less space.

- `Resave VTF files (autorefresh)`  
  Resave `.vtf` files to force Garry's Mod to refresh cached texture data after edits.

- `Convert images to PNG`  
  Convert supported image types such as `.jpg`, `.bmp`, `.tga`, `.gif`, `.tiff`, and `.webp` into `.png` for a more consistent workflow.

- `Convert DDS to PNG`  
  Convert `.dds` textures into `.png` so they are easier to inspect, edit, and reuse in interface-focused asset pipelines.

- `Remove PNG Ports`  
  Remove `.png` files that appear to be duplicate DDS ports when a same-name `.dds` already exists beside them.

### Cleanup Utilities

- `Scan unused model formats`  
  Find unused model sidecar files such as `.dx80.vtx`, `.xbox.vtx`, `.sw.vtx`, and `.360.vtx` that Garry's Mod does not use.

- `Remove unused model formats`  
  Delete those unused model sidecar files to cut dead weight from content packs.

- `Remove files already in game (HL2/CSS)`  
  Remove files already shipped by base Garry's Mod or mounted game content to avoid bundling duplicates.

- `Remove empty folders`  
  Clean up empty directories left behind after removal and compression passes.

- `Find and copy content used by .bsp`  
  Scan a map and copy the files it references into a new folder to help with map packing and dependency collection.

- `Find unused material textures`  
  Report `.vtf` textures in model material folders that are not referenced by Lua-used models.

- `Remove unused material textures`  
  Delete unused `.vtf` textures from model material folders when they are not referenced by Lua-used models.

- `Find missing materials`  
  Generate a report of model material paths that are missing from the addon and optionally check Garry's Mod fallback content.

- `Recover Missing Materials From Content Packs`  
  Search content packs for missing `.vmt` and `.vtf` files and copy recovered matches into the working content folder.

- `Find models with missing textures`  
  List models whose material folders or referenced texture files are missing so broken assets are easier to track down.

- `Remove comments from Lua files`  
  Remove single-line and inline Lua comments while preserving long comment blocks, then pretty-print with `glualint`.

### Audio Compression

- `Convert sound to OGG`  
  Convert supported `.wav` and `.mp3` files into `.ogg` to reduce size and standardize audio delivery.

- `Trim silence`  
  Remove empty audio at the start and end of files so sounds are tighter and waste less space.

- `Re-encode existing OGGs`  
  Re-encode `.ogg` files at a chosen bitrate to shrink oversized audio that was encoded too aggressively.

- `Resample`  
  Resample `.ogg` files to 44.1 kHz when needed for a more consistent audio set.

- `Normalize the volume`  
  Normalize loudness across audio files so packs sound more consistent in-game.

- `Strip metadata from audio`  
  Remove embedded tags, album art, and other metadata from audio files without affecting playback quality.

- `Run Full Sound Workflow`  
  Run the main sound cleanup pipeline in one step, including OGG conversion and metadata stripping.

### File Merging

- `Run Addon Merge / Split Workflow`  
  Merge addon folders into one destination and optionally split the merged result into numbered content packs.

- `Import Content Packs Into Content Folder`  
  Detect the real content root inside each content pack and copy files into the current content folder using the correct layout.

- `Run Full Workflow (Except Merge)`  
  Run the primary cleanup workflow on the current content folder without importing or merging content packs first.

- `Run Full Image Workflow`  
  Run the main image and texture workflow in one pass, including conversion, VTF optimization, and PNG clamping.

### Benchmark

- `Benchmark Textures`  
  Clone the current content folder, run the texture and image workflow on the clone, report the before and after size, and delete the clone.

- `Benchmark Cleanup`  
  Clone the current content folder, run the cleanup workflow on the clone, report the before and after size, and delete the clone.

- `Benchmark Audio`  
  Clone the current content folder, run the audio workflow on the clone, report the before and after size, and delete the clone.

- `Benchmark Full Workflow`  
  Clone the current content folder, run the full workflow on the clone, report the before and after size, and delete the clone.

### Backup

- `Back Up Content Folder`  
  Create a timestamped backup copy of the currently selected content folder under the app's `backups/content_folder` directory.

- `Load Content Folder Backup`  
  Restore a saved content-folder backup into the current content folder after confirmation.

- `Back Up Content Packs`  
  Create a timestamped backup copy of the currently selected content-packs folder under the app's `backups/content_packs` directory.

- `Load Content Packs Backup`  
  Restore a saved content-packs backup into the current content-packs folder after confirmation.

## Requirements

- Windows is the primary supported platform for the full desktop workflow
- Python 3.10 or newer
- Git
- Internet access on first run if `ffmpeg.exe` needs to be downloaded automatically

## Built for Lilia

If you are building a Garry's Mod roleplay server, you can pair this tool with [Lilia](https://github.com/LiliaFramework/Lilia), a full framework for creating and running your own gamemode.

Lilia is a strong fit if you want:

- A ready starting point for building a custom roleplay experience
- A framework you can extend with your own schema, systems, and server content
- Better control over how your content pack and gamemode are organized together

Use this optimization tool to clean up the addons, maps, materials, and sounds around your server content, then build the gameplay side on top of Lilia. This will ensure high performance, both clientside and serverside.

## Contributing

We welcome improvements to both the tool and its supporting utilities. To contribute:

1. Fork the repository
2. Create a feature branch
3. Make your changes and test them
4. Open a pull request with a clear explanation of what changed

## Credits

- Uses [sourcepp](https://github.com/craftablescience/sourcepp) for Source-format handling
- Inspired by and uses features from [gm_addon_optimization_tricks](https://github.com/wrefgtzweve/gm_addon_optimization_tricks) by wrefgtzweve
