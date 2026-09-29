"""Write a PyInstaller version file, so the Windows exe's carry product name and version.

SignPath (code signing) checks these file details before it signs: the product name must be
the project's, the version that of the build.

    python packaging/versionfile.py build/version.txt
"""
import re
import sys

from anonymate import __version__

# Windows wants four numbers; 0.1.0rc1 becomes 0.1.0.0, the text fields keep 0.1.0rc1.
numbers = [int(n) for n in re.match(r"[\d.]*\d", __version__).group().split(".")][:3]
numbers = tuple(numbers + [0] * (4 - len(numbers)))

strings = {
    "CompanyName": "Henri ter Hofte",
    "FileDescription": "AnonyMate: herleidbaarheidstoets voor woningdata",
    "FileVersion": __version__,
    "InternalName": "anonymate",
    "LegalCopyright": "© 2026 Henri ter Hofte, EUPL-1.2",
    "ProductName": "AnonyMate",
    "ProductVersion": __version__,
}
entries = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())

with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {entries}])]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])
  ]
)
""")
