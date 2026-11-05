# Sales Chess Player

A local Windows chess assistant with automatic board finding, plain-language move instructions, promotion-choice detection, and Balanced, Aggressive, and Fastest Checkmate selections. Separate Play, Board, Appearance, and Configs tabs keep its controls organized. Choose from seven built-in themes or make your own, save and load named setting configs, pick a background image, and turn animations off. Preferences save automatically, and the Discord button opens `discord.gg/rMkAf7tW9e`. Stockfish 19 runs entirely on your computer.

## Quick start

1. Open **SalesChessPlayer.exe**. The single-file executable includes its piece artwork and Stockfish engine.
2. Open a Chess.com analysis or computer-practice board with **Neo** pieces. Keep all 64 squares visible and move the Sales Chess Player panel beside the board.
3. Click **Find board**. It looks for a board on the desktop and starts scanning automatically. **Select manually** lets you drag around just the 64 squares if automatic finding fails. Boards must be at least 240 pixels across; 480 or more is recommended.
4. The recommendation names the piece and destination, for example **Knight to f3**, followed by **Move your knight: g1 → f3**. An arrow marks the move on the actual board. The optional **Auto-play moves** control clicks the recommended move for the color at the bottom; use it only for computer practice.

**Ctrl+Alt+P** pauses/resumes scanning unless another app already reserved the shortcut. The Pause/Start button also works. Close the app to end scanning and the engine. Reselect/find the board after moving the browser, scrolling, zooming or resizing.

## Native DLL API

The optional DLL is a native C ABI launcher/control library for C++ and C# hosts. It starts or closes the desktop app as a separate process; the GUI and chess engine remain in **SalesChessPlayer.exe**. Put the DLL beside the executable.

- **SalesChessPlayer.dll** is x64 and suits the default 64-bit C# process and x64 C++ hosts.
- **SalesChessPlayer-x86.dll** is for 32-bit C# or C++ hosts. The DLL and host must have the same architecture.

The exported calls are `SalesChessPlayer_Start` (1 started, 0 already running, -1 failed), `SalesChessPlayer_Stop(timeoutMs)` (1 stopped, 0 not running, -1 timed out/failed), `SalesChessPlayer_IsRunning`, and `SalesChessPlayer_GetLastErrorCode`. Stop requests a normal window close; it does not forcibly terminate the app. The C header and implementation are in `SalesChessPlayerDll.h` and `SalesChessPlayerDll.c`.

C# P/Invoke declarations:

```csharp
using System.Runtime.InteropServices;

internal static class SalesChessPlayerNative
{
    [DllImport("SalesChessPlayer.dll", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int SalesChessPlayer_Start();

    [DllImport("SalesChessPlayer.dll", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int SalesChessPlayer_Stop(uint timeoutMs);

    [DllImport("SalesChessPlayer.dll", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int SalesChessPlayer_IsRunning();

    [DllImport("SalesChessPlayer.dll", CallingConvention = CallingConvention.Cdecl)]
    internal static extern uint SalesChessPlayer_GetLastErrorCode();
}
```

C++ hosts can load the same exports with `LoadLibraryW` and `GetProcAddress`; `SalesChessPlayerDll.h` contains their C ABI declarations:

```cpp
HMODULE dll = LoadLibraryW(L"SalesChessPlayer.dll");
if (dll) {
    using StartFn = int(__cdecl*)(void);
    auto start = reinterpret_cast<StartFn>(GetProcAddress(dll, "SalesChessPlayer_Start"));
    if (start) {
        int result = start(); // 1 started, 0 already running, -1 failed
    }
    FreeLibrary(dll);
}
```

## Playing style

- **Balanced** chooses Stockfish's highest-ranked line in the allocated thinking time.
- **Aggressive** compares up to three engine lines. It favors checks, captures, advancing pieces and pressure around the enemy king, considering only alternatives within **0.35 pawns** of the top engine score. A forced-mate result takes precedence. This is a preference among close engine choices, not a claim that every suggested move is an attack or that the alternative is equally strong. Open the **Board** tab to see the continuation and any score difference.
- **Fastest Checkmate** compares up to three engine lines, chooses the shortest forced mate found, and shows the strongest line when the search finds no forced win. Increase thinking time to give Stockfish more time to find a mate; this is a search result, not a guarantee that it found the globally shortest possible mate.

Longer thinking can improve analysis. The result is the best move found in that search, not a mathematical guarantee of perfect play.

## Promotion chooser

The app recognizes the vertical **queen / knight / rook / bishop** chooser shown in the supplied reference. When your pawn reaches the last rank, it compares the legal promotion choices for that pawn and says, for example, **Promote to knight**. A green outline highlights the actual menu item to choose. It supports white/black promotions, either board orientation, and underpromotion. It resumes ordinary move tracking after you choose.

**Start scanning before you advance the pawn.** The popup hides part of the board. If you join while it is already open and the app has no position history, it identifies the chooser but asks for the complete FEN from **before the pawn move** instead of inventing the hidden position. Load it under **Board → Load FEN**, then start scanning with the menu visible.

## Board tab

Use this tab to configure board reading and review analysis details:

- The recognized-board preview and engine continuation.
- Automatic bottom-color detection, with **Black at bottom** available as a manual override.
- Thinking time, from 0.2 to 15 seconds per position.
- **Load FEN** for a midgame position, **Reset** for a new starting position, and **Try demo** for a local test board.

Use the **Auto-play moves** checkbox on the **Play** tab to click recommendations for the detected bottom-side color during computer practice. It waits for the opponent's turn.

## Appearance and saved configs

Theme, layout, analysis, and board options save automatically as you change them. Use the **Config** controls to save a reusable snapshot with your own name, load it later, or delete it. Seven built-in themes are available: Black & White, White & Black, Slate, Ocean, Emerald, Sunset and Violet. **Edit custom colors** lets you choose your own background, panel, border, text, accent, and star colors. A selected background image is remembered by its file path, so keep that image in place. With an image selected, buttons become transparent and use black-outlined white labels. Turn off **Enable background and opening animations** to stop the moving stars and unfold effect.

A starting position is initialized automatically. For an arbitrary midgame position, paste the full six-field FEN: pixels cannot establish the side to move, castling rights or en passant rights. One move, or a unique pair of moves, can be followed between captures, and the app can step back through positions it has already seen. Load the current FEN after a larger jump or board edit.

## Recognition limits

Ordinary chess and Neo artwork are supported; other piece themes, Chess960 and variants are not. Normal colored square highlights are supported. Two consistent clear frames are required before analysis. An unclear frame hides the advice overlay. Close unrelated menus, remove user-drawn arrows and let animations finish. A promotion chooser is handled specifically; arbitrary dialogs obscuring pieces are not.

Automatic finding looks for a large alternating board; use manual selection if several boards or similar patterns are visible. Keep the selected board entirely visible. An unlocked Windows desktop is required. Scaled/multiple-monitor or remote-display setups may need manual selection.

## Privacy and appropriate use

Analysis and recognition run locally. Find board and manual selection briefly capture the desktop into memory; ongoing scanning captures only the selected board region. When **Auto-play moves** is enabled, the app clicks moves on the selected board. The app does not save or transmit screenshots, positions, account information or telemetry, and requires no account login or API key.

Use for study, analysis or computer-bot practice. Chess.com prohibits engine assistance against other users: [Fair Play policy](https://www.chess.com/legal/fair-play). Sales Chess Player is not affiliated with Chess.com or Stockfish.

## Getting the engine

The Stockfish binary is not stored in this repository because of its size. Download `stockfish-windows-x86-64.zip` (universal build) from the [Stockfish 19 release](https://github.com/official-stockfish/Stockfish/releases/tag/sf_19) and put `stockfish-windows-x86-64-universal.exe` in `engine/stockfish/`. The license, source and documentation for Stockfish are already in that folder.

The DLL binaries are not committed either. Build them from `SalesChessPlayerDll.c` with `SALES_CHESS_PLAYER_DLL_BUILD` defined, for example `cl /LD /DSALES_CHESS_PLAYER_DLL_BUILD SalesChessPlayerDll.c /Fe:SalesChessPlayer.dll user32.lib`.

## Source, tests and rebuild

Python 3.10 or newer is required only for editing the source, not for the supplied executable:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest -v test_chesslens.py
```

To rebuild, install `pyinstaller==6.22.3` into that environment, then run `.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath . --workpath ../../work/rebuild-v2 ChessLens.spec`. The supplied configuration excludes unrelated system-library copies from the build machine and keeps the C++ runtime consistent. The generated one-file executable embeds the piece artwork and Stockfish engine.

`SalesChessPlayer.exe --self-test report.json` checks the packaged recognition, board finder, promotion detector, all three playing styles and real Stockfish analysis, without opening windows or capturing the screen. Third-party source, attribution and licenses are described in THIRD-PARTY.md and included in `licenses/` and `engine/stockfish/`.
