from jevpip.signals import SignalPolicy, classify_research_signal


def response(up=0.7, down=0.1, flat=0.2, noise=0.2, reversal=0.1, trend=2.0):
    return {
        "answers": {
            "direction": {
                "type": "choice",
                "choice": "UP",
                "confidence": 0.8,
                "probabilities": {"UP": up, "DOWN": down, "FLAT": flat},
            },
            "market_is_noisy": {"type": "noul", "noul": noise},
            "reversal_risk": {"type": "noul", "noul": reversal},
            "trend_strength": {"type": "score", "score": trend},
        }
    }


def test_long_candidate():
    signal, detail = classify_research_signal(response(), 1.0, SignalPolicy())
    assert signal == "LONG"
    assert round(detail["long_margin"], 4) == 0.6


def test_noise_vetoes_candidate():
    signal, _ = classify_research_signal(response(noise=0.9), 1.0, SignalPolicy())
    assert signal == "WAIT"


def test_spread_is_code_owned_veto():
    signal, _ = classify_research_signal(response(), 9.0, SignalPolicy())
    assert signal == "WAIT"
