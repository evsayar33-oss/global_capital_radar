import unittest
from datetime import date
from horizon_evaluation import evaluate

class EvaluationTest(unittest.TestCase):
    def test_mature_only_direction_and_overlap(self):
        day,entry,end = (date(2026,11,n) for n in (1,2,9))
        h=dict(action="AZALTMA ADAYI",confirmation="YÖN UYUMLU")
        report={"assets":[dict(symbol="GLD",horizons={"1H":h,"1A":h})]}
        prices={"SGOV":{entry:(1,1),end:(1,1)},"GLD":{entry:(1,1),end:(1,.9)}}
        result=evaluate([(day,report)]*2,prices,date(2026,11,10))
        self.assertEqual(len(result),1)
        self.assertAlmostEqual(result[0][2],10)
