# Third-party components

- **Stockfish 19**, GPL v3. Official Windows universal distribution, including its license, source, build scripts and documentation, is preserved under `engine/stockfish/`. Upstream: https://github.com/official-stockfish/Stockfish/releases/tag/sf_19 . Stockfish's source refers to its publicly downloadable neural network by hash and includes the download/build scripts.
- **python-chess / chess**, GPL v3 or later. https://github.com/niklasf/python-chess . The library implements chess rules and UCI communication. The ChessLens application source is provided under GPL v3 or later; the same license is supplied in LICENSE.txt.
- **PySide6 / Qt**, LGPL v3 / GPL v3 / commercial options. https://doc.qt.io/qtforpython-6/licenses.html . Used under GPL v3 for this application. Source and packages: https://download.qt.io/official_releases/QtForPython/ .
- **MSS**, MIT. https://github.com/BoboTiG/python-mss .
- **OpenCV**, Apache 2.0. https://github.com/opencv/opencv . **opencv-python-headless** packaging, MIT: https://github.com/opencv/opencv-python .
- **NumPy**, BSD 3-clause. https://github.com/numpy/numpy .
- **PyInstaller** bootloader, GPL v2 or later with an exception for built applications. https://pyinstaller.org/en/stable/license.html .
- **Chess.com Neo piece artwork**, retrieved from Chess.com's publicly served theme assets, `https://images.chesscomfiles.com/chess-themes/pieces/neo/150/{piece}.png`, to recognize and preview that theme. Artwork belongs to its respective rights holders and is not covered by the application source license. No independent redistribution rights are asserted. The app is prepared for the requesting user's local use.

The `licenses/` directory includes the installed Python distributions' license texts and metadata. The dependency versions used are recorded in requirements.txt. Python itself is distributed under the Python Software Foundation license; the frozen executable contains a Python interpreter.
