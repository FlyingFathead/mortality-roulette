import tempfile
import unittest
import zipfile
from pathlib import Path

from mortality_roulette_core.hmd import (
    HMD_OPEN_AGE,
    HmdDataError,
    find_hmd_source,
    load_hmd_period_life_table,
)


TABLE = """Synthetic HMD table\n\n  Year          Age         mx       qx    ax      lx      dx      Lx       Tx     ex\n  1900           0      0.10000  0.09000  0.30  100000    9000   90000  1000000  10.00\n  1900           1      0.02000  0.01980  0.50   91000    1802   90099   910000  10.00\n  1900         110+      0.50000  1.00000  1.00       1       1       1        1   1.00\n  1901           0      0.08000  0.07500  0.30  100000    7500   92500  1000000  10.00\n  1901           1      0.01500  0.01490  0.50   92500    1378   91811   925000  10.00\n"""


def make_country_zip(path: Path, code: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{code}/STATS/mltper_1x1.txt", TABLE)
        zf.writestr(f"{code}/STATS/fltper_1x1.txt", TABLE.replace("0.09000", "0.08000", 1))
        zf.writestr(f"{code}/InputDB/{code}death.txt", "not used\n")


class HmdReaderTests(unittest.TestCase):
    def test_reads_direct_country_zip_and_excludes_open_age(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "FIN.zip"
            make_country_zip(archive, "FIN")
            table = load_hmd_period_life_table(
                archive, country_code="FIN", needed_sexes={"male", "female"}
            )
            self.assertEqual(table.country_code, "FIN")
            self.assertEqual(table.min_year, 1900)
            self.assertEqual(table.max_year, 1901)
            self.assertEqual(table.max_exact_age, 1)
            self.assertEqual(table.source, str(archive))
            self.assertAlmostEqual(table.data["male"][1900][0], 0.09)
            self.assertAlmostEqual(table.data["female"][1900][0], 0.08)
            self.assertNotIn(HMD_OPEN_AGE, table.data["male"][1900])

    def test_finds_country_archive_in_default_style_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive = base / "CAN.zip"
            make_country_zip(archive, "CAN")
            self.assertEqual(find_hmd_source(base, "CAN"), archive)
            self.assertIsNone(find_hmd_source(base, "FIN"))

    def test_does_not_read_different_country_archive(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "USA.zip"
            make_country_zip(archive, "USA")
            with self.assertRaises(HmdDataError):
                load_hmd_period_life_table(
                    archive, country_code="FIN", needed_sexes={"male"}
                )

    def test_reads_extracted_hmd_country_tree(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stats = base / "CAN" / "STATS"
            stats.mkdir(parents=True)
            (stats / "mltper_1x1.txt").write_text(TABLE, encoding="utf-8")
            table = load_hmd_period_life_table(
                base, country_code="CAN", needed_sexes={"male"}
            )
            self.assertEqual(table.min_year, 1900)
            self.assertEqual(table.max_year, 1901)
            self.assertEqual(table.source, str(base))
            self.assertAlmostEqual(table.data["male"][1901][1], 0.0149)


if __name__ == "__main__":
    unittest.main()
