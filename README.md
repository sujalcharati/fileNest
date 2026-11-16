# FileNest

**Instant file search for Windows.** Press **Alt+Space**, type any part of a file or
folder name, and jump straight to it, however deep in nested folders it's hidden.

- Finds any file across your drives in milliseconds (tested: 720,000 files, 5–15 ms per search)
- Stays up to date by itself as you create, rename, move or delete files
- Opens the file, or opens its folder in File Explorer with the file selected
- Native Windows 11 look: frosted-glass window, follows your dark/light mode and accent colour
- 100% offline: your file list never leaves your computer

---

## Requirements

| | |
|---|---|
| **Operating system** | Windows 10 or 11 (frosted-glass effect needs Windows 11 22H2+; older versions get a solid window) |
| **Python** | **3.12 or newer** |
| **Disk space** | ~350 MB for the dependencies, plus ~300–500 MB for the index (depends on how many files you have) |
| **Git** | Optional, only needed for step 2 option A |

---

## Installation

### 1. Install Python (skip if you already have 3.12+)

Check first. Open **Command Prompt** and run:

```
python --version
```

If it says `Python 3.12.x` or higher, skip to step 2. Otherwise:

1. Download Python from <https://www.python.org/downloads/>.
2. Run the installer and **tick "Add python.exe to PATH"** at the bottom of the first screen.
3. Click **Install Now**.
4. Close and reopen Command Prompt, then run `python --version` again to confirm.

### 2. Download FileNest

**Option A, with Git:**

```
git clone <REPO_URL> FileNest
cd FileNest
```

**Option B, without Git:** on the repository page click **Code → Download ZIP**, then
right-click the ZIP → **Extract All**, and open the extracted `FileNest` folder.

> Put the folder somewhere **permanent with a short path** (e.g. `C:\Users\<you>\FileNest`
> or `Documents\FileNest`). The folder path must be under ~90 characters, because some
> files in the UI library have very deep paths and Windows limits full paths to 260 characters.
> If you move the folder later, run `setup.bat` again.

### 3. Run the setup

Double-click **`setup.bat`** in the FileNest folder.

It will:
1. check that Python 3.12+ is installed,
2. create a private Python environment in a `.venv` folder (nothing is installed system-wide),
3. install the two libraries FileNest needs (`PySide6-Essentials` for the window, `watchdog` for live updates),
4. start FileNest.

This takes 1–3 minutes the first time.

<details>
<summary>Prefer the command line? Do the same steps manually.</summary>

```
cd path\to\FileNest
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\pythonw FileNest.pyw
```
</details>

### 4. First launch: building the index

The first time FileNest runs, it scans your drives to build its index. The search window
shows a spinner and a live count. **This takes about a minute and happens only once.**
After that every search is instant, and the index updates itself automatically.

### 5. Make it start with Windows (recommended)

FileNest can only track file changes while it's running. Right-click the **FileNest icon**
in the system tray (bottom-right, near the clock; it may be under the **^** arrow) and tick
**Start with Windows**.

You're done. Press **Alt+Space** anywhere to search.

---

## Using FileNest

| Key | Action |
| --- | --- |
| `Alt+Space` | Open / close the search bar, from anywhere in Windows |
| `↑` `↓` | Move through results |
| `Enter` | Open the file |
| `Ctrl+Enter` | Show it in its folder (File Explorer opens with the file selected) |
| `Ctrl+C` | Copy the full path |
| `Tab` / `Shift+Tab` | Switch filter: All, Files, Folders, Documents, Images, Media, Code, Archives, Apps |
| `Esc` | Clear the search, then close |
| Right-click a result | Open, show in folder, copy path, copy name |

**Search tips**
- Type any part of the name: `xyz` finds `old_xyz_final.pdf`.
- Several words must all match: `resume pdf`.
- A word containing `\` matches the folder path: `college\ notes`.
- With an empty search box, FileNest shows your recently modified files.

**Tray menu** (right-click the tray icon): Search files · Rebuild index now ·
Start with Windows · Open settings file · Quit.

**Starting it manually** (if you didn't enable *Start with Windows*): double-click `FileNest.bat`.

---

## Settings

Tray icon → **Open settings file** (or open `%LOCALAPPDATA%\FileNest\settings.json`).
Restart FileNest after editing.

| Setting | What it does |
|---|---|
| `hotkeys` | Shortcuts to try, in order. The first one not used by another app is used. |
| `drives` | Drives to index, e.g. `["C:\\", "D:\\"]`. Empty = all internal drives. |
| `extra_folders` | Extra folders to index, e.g. on a USB or network drive. |
| `exclude_folder_names` | Folder names skipped everywhere (`node_modules`, `.git`, …). |
| `exclude_paths` | Full paths skipped (Windows, Program Files, browser caches, …). |
| `rescan_every_hours` | How often a full background re-scan runs (default 6). |
| `acrylic` | `false` gives a solid background instead of frosted glass. |

---

## Updating

- **Git:** in the FileNest folder run `git pull`, then double-click `setup.bat`.
- **ZIP:** download the new ZIP, extract it over the old folder, then double-click `setup.bat`.

Quit FileNest from the tray first. Your index and settings are kept.

---

## Uninstalling

1. Right-click the tray icon, **untick "Start with Windows"**, then click **Quit FileNest**.
2. Delete the FileNest folder.
3. Delete the index and settings: press `Win+R`, paste `%LOCALAPPDATA%\FileNest`,
   press Enter, and delete that folder.

FileNest installs nothing else on your system.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `setup.bat` says the path is too long, or pip shows `No such file or directory … long path` | Move the FileNest folder to a shorter path (e.g. `C:\Users\<you>\FileNest`), delete the `.venv` folder inside it, and run `setup.bat` again. Alternatively, enable long paths: run PowerShell **as administrator**, then `New-ItemProperty -Path HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force`, and restart. |
| `setup.bat` says Python was not found | Reinstall Python and tick **"Add python.exe to PATH"**, then reopen the folder and run `setup.bat` again. |
| Alt+Space does nothing | Another app owns that shortcut (often **PowerToys Run**). Hover over the tray icon to see which shortcut FileNest got, or change `hotkeys` in the settings. |
| A file I just made doesn't show up | Was FileNest running when you made it? If not, use tray → **Rebuild index now**. |
| A folder never shows up | It may be excluded. Check `exclude_paths` and `exclude_folder_names` in the settings. |
| Window has no frosted-glass effect | Needs Windows 11 22H2 or newer. On older versions a solid window is used instead. |
| Something else | Check the log at `%LOCALAPPDATA%\FileNest\filenest.log`. |

---

## How it works

- **`filenest/indexer.py`** scans every drive once into a SQLite database
  (`%LOCALAPPDATA%\FileNest\index.db`). File names are split into 3-letter pieces
  (a *trigram* index), so finding any substring among hundreds of thousands of names is a
  lookup, not a scan.
- **`filenest/watcher.py`** subscribes to Windows' file-change notifications and updates
  only the affected rows, within about 2 seconds of a change.
- **`filenest/ui.py`** is the search window (PySide6 / Qt).
- **`filenest/app.py`** handles the tray icon, global hotkey, single-instance check and
  background re-scans.

**Command-line tools** (run inside the FileNest folder):

```
.venv\Scripts\python -m filenest.cli scan          # rebuild the index
.venv\Scripts\python -m filenest.cli find resume   # search from the terminal
```

### Project layout

```
FileNest/
├── setup.bat          one-click install
├── FileNest.bat       start FileNest
├── FileNest.pyw       entry point
├── requirements.txt   Python dependencies
└── filenest/
    ├── app.py         tray, hotkey, background work
    ├── ui.py          search window
    ├── indexer.py     scanning + search index
    ├── watcher.py     live file-change tracking
    ├── theme.py       colours (dark/light, accent)
    ├── winfx.py       Windows APIs (acrylic, hotkey, startup)
    ├── filetypes.py   file categories and filters
    ├── icon.py        app icon
    └── cli.py         command-line tools
```
#   f i l e N e s t  
 