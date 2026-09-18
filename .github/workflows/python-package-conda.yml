name: Build Windows EXE

on:
  workflow_dispatch:
  push:
    branches: [ main, master ]

jobs:
  build:
    runs-on: windows-latest

    steps:
    - name: Checkout
      uses: actions/checkout@v4

    - name: Setup Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.12'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install pyinstaller keyboard

    - name: Build EXE
      run: |
        pyinstaller --onefile --noconsole --name MiniTranslator --hidden-import keyboard mini_translator.py

    - name: Upload artifact
      uses: actions/upload-artifact@v4
      with:
        name: MiniTranslator-Windows
        path: dist/MiniTranslator.exe
