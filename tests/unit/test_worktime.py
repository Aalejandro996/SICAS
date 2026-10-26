"""Horario laboral: feriados de Venezuela, apertura y cierre, y tiempo hábil para los promedios."""
import unittest
from datetime import date, datetime

from app.core import worktime as w

T = w.TZ
NO_DB = []          # sin feriados decretados (no consulta la base)


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=T)


class HolidaysTest(unittest.TestCase):
    def test_easter_and_movable_holidays(self):
        self.assertEqual(w.easter(2026), date(2026, 4, 5))
        self.assertEqual(w.easter(2027), date(2027, 3, 28))
        h = w.holidays(2026, NO_DB)
        for d in (date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 2), date(2026, 4, 3)):
            self.assertIn(d, h)
        for d in (date(2026, 1, 1), date(2026, 4, 19), date(2026, 5, 1), date(2026, 6, 24), date(2026, 7, 5), date(2026, 7, 24),
                  date(2026, 10, 12), date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31)):
            self.assertIn(d, h)
        self.assertEqual(len(h), 14)

    def test_decreed_and_not_observed(self):
        extra = [{"holiday_date": date(2026, 11, 2), "name": "Decreto", "kind": "DECREE", "observed": True},
                 {"holiday_date": date(2026, 10, 12), "name": "Día de la Resistencia Indígena", "kind": "FIXED", "observed": False}]
        h = w.holidays(2026, extra)
        self.assertIn(date(2026, 11, 2), h)
        self.assertNotIn(date(2026, 10, 12), h)


class ScheduleTest(unittest.TestCase):
    def test_open_hours(self):
        self.assertTrue(w.is_open(at(2026, 10, 26, 8, 0), NO_DB))          # lunes 8:00
        self.assertTrue(w.is_open(at(2026, 10, 26, 16, 59), NO_DB))
        self.assertFalse(w.is_open(at(2026, 10, 26, 17, 0), NO_DB))        # 17:00 cierra
        self.assertFalse(w.is_open(at(2026, 10, 26, 7, 59), NO_DB))
        self.assertFalse(w.is_open(at(2026, 10, 31, 10), NO_DB))           # sábado
        self.assertFalse(w.is_open(at(2026, 10, 12, 10), NO_DB))           # feriado
        self.assertTrue(w.is_open(datetime(2026, 10, 26, 13, 0), NO_DB))   # 13:00 UTC = 9:00 en Caracas

    def test_next_open_skips_weekend_and_holidays(self):
        self.assertEqual(w.next_open(at(2026, 10, 30, 17, 30), NO_DB), at(2026, 11, 2, 8))     # viernes -> lunes
        self.assertEqual(w.next_open(at(2026, 12, 23, 18), NO_DB), at(2026, 12, 28, 8))        # 24 y 25 feriados, fin de semana
        self.assertEqual(w.next_open(at(2026, 10, 26, 6), NO_DB), at(2026, 10, 26, 8))

    def test_business_seconds(self):
        self.assertEqual(w.business_seconds(at(2026, 10, 26, 8), at(2026, 10, 26, 17), NO_DB), 9 * 3600)
        self.assertEqual(w.business_seconds(at(2026, 10, 26, 7), at(2026, 10, 26, 20), NO_DB), 9 * 3600)
        self.assertEqual(w.business_seconds(at(2026, 10, 30, 16), at(2026, 11, 2, 9), NO_DB), 2 * 3600)   # viernes 16 a lunes 9
        self.assertEqual(w.business_seconds(at(2026, 10, 9, 16), at(2026, 10, 13, 9), NO_DB), 2 * 3600)   # lunes 12 feriado
        self.assertEqual(w.business_seconds(at(2026, 10, 26, 10), at(2026, 10, 26, 9), NO_DB), 0)
        self.assertEqual(w.business_seconds(at(2026, 10, 26, 0), at(2026, 11, 2, 0), NO_DB), 5 * 9 * 3600)


if __name__ == "__main__":
    unittest.main()
