"""
BingX Institutional Suite v45.6 (HOTFIX APPLIED)
Enforces strict Hard Block Priority, Volume Risk Precedence, and Counter-Trend Safeguards before MARKET execution.
"""

class BingXInstitutionalSuite:
    def __init__(self, threshold=72):
        self.threshold = threshold

    def evaluate_trade(self, context: dict) -> dict:
        """
        Evaluates trade context through strict hierarchical Hard Risk Gates,
        ensuring BLOCKED statuses (Volume Risk, Counter-Trend, etc.) 
        take absolute precedence over Core Evidence and Score.
        """
        
        # --- 1. HARD BLOCK PRIORITY ENGINE ---
        
        # Gate 1: Extreme Volatility
        if context.get('extreme_volatility', False):
            return self._format_response("Extreme Volatility", "HARD BLOCK", "NO TRADE")
            
        # Gate 2: Invalid OB (Order Block)
        elif context.get('invalid_ob', False):
            return self._format_response("Invalid OB", "HARD BLOCK", "NO TRADE")
            
        # Gate 3: Price Too Far / Chase (Anti-Chase Failed)
        elif context.get('anti_chase_failed', False) or context.get('price_too_far_or_chase', False):
            return self._format_response("Price Too Far / Chase", "HARD BLOCK", "NO TRADE")
            
        # Gate 4: Invalid SL (Stop Loss)
        elif context.get('invalid_sl', False) or context.get('risk_invalid', False):
            return self._format_response("Invalid SL", "HARD BLOCK", "NO TRADE")
            
        # Gate 5: R:R < Minimum
        elif context.get('rr_below_minimum', False) or context.get('rr_ratio', 2.0) < context.get('min_rr', 1.5):
            # Respect exception logic: check if same direction allows lower RR (e.g., 1.5) vs counter-trend (2.0)
            is_same_direction = context.get('bias_4h') == context.get('bias_1h')
            min_required = 1.5 if is_same_direction else 2.0
            if context.get('rr_ratio', 2.0) < min_required:
                return self._format_response("R:R < minimum", "HARD BLOCK", "NO TRADE")
            
        # Gate 6: Stale Signal
        elif context.get('stale_signal', False):
            return self._format_response("Stale Signal", "HARD BLOCK", "NO TRADE")
            
        # Gate 7: Real-Time Revalidation Failed
        elif context.get('real_time_revalidation_failed', False) or context.get('real_time_validation_failed', False):
            return self._format_response("Real-Time Revalidation Failed", "HARD BLOCK", "NO TRADE")
            
        # Gate 8: Counter-Trend Risk Block (including Extreme Weak Volume + Counter-Trend checks)
        elif self._is_counter_trend_blocked(context):
            return self._format_response("Counter-Trend Risk Block", "HARD BLOCK", "NO TRADE")
            
        # Gate 9: Volume Risk Block (Absolute Precedence)
        elif context.get('volume_risk_status') == "BLOCKED" or context.get('volume_risk_block', False):
            block_reason = context.get('volume_risk_detail', "Volume Risk: BLOCKED - COUNTER TREND")
            return self._format_response(block_reason, "HARD BLOCK", "NO TRADE")
            
        # --- 2. SECONDARY GATES (Core Evidence & Score) ---
        
        # Gate 10: Core Evidence Check
        elif not context.get('core_evidence_pass', True):
            return self._format_response("Core Evidence Failed", "EVIDENCE CHECK", "NO TRADE")
            
        # Gate 11: Score Threshold Check
        elif context.get('score', 0) < context.get('threshold', self.threshold):
            return self._format_response(f"Score {context.get('score', 0)} Below Threshold {context.get('threshold', self.threshold)}", "SCORE CHECK", "NO TRADE")
            
        # --- 3. EXECUTION ---
        else:
            return {
                "Volume Risk": "ACCEPTABLE",
                "Final Gate": "EXECUTION",
                "Decision": "MARKET",
                "Reason": "All Hard Gates, Core Evidence, and Score Thresholds Passed Successfully."
            }

    def _is_counter_trend_blocked(self, context: dict) -> bool:
        """
        Evaluates counter-trend and extremely weak volume criteria.
        Returns True if the trade must be blocked due to counter-trend risk rules.
    
        Same-Direction Exception: Does NOT block if 4H Bias matches 1H Bias (and other standard criteria met).
        """
        bias_4h = context.get('bias_4h')
        bias_1h = context.get('bias_1h')
        volume_state = context.get('volume_state', 'NORMAL') # e.g., 'EXTREMELY_WEAK', 'NORMAL'
        is_counter_trend = context.get('is_counter_trend', False)
        
        # High Volatility + Counter-Trend + Extremely Weak Volume check
        if bias_4h != bias_1h and volume_state == 'EXTREMELY_WEAK' and is_counter_trend:
            # Check strict override conditions for counter-trend execution
            mss_bos = context.get('mss_bos', False)
            liquidity_sweep = context.get('liquidity_sweep', False)
            strong_displacement = context.get('strong_displacement', False)
            valid_ob = context.get('valid_ob', False)
            entry_location_excel = context.get('entry_location') == 'EXCELLENT'
            rr_met = context.get('rr_ratio', 0) >= 2.0
            anti_chase_pass = not context.get('anti_chase_failed', False)
            reval_pass = not context.get('real_time_revalidation_failed', False)
            
            # If any required exception condition fails, trigger block
            if not (mss_bos and liquidity_sweep and strong_displacement and valid_ob and entry_location_excel and rr_met and anti_chase_pass and reval_pass):
                return True
                
        return context.get('counter_trend_risk_blocked', False)

    def _format_response(self, volume_risk_msg: str, final_gate: str, decision: str) -> dict:
        return {
            "Volume Risk": volume_risk_msg,
            "Final Gate": final_gate,
            "Decision": decision
        }

# --- REGRESSION TEST SUITE VERIFICATION ---
if __name__ == "__main__":
    suite = BingXInstitutionalSuite(threshold=72)

    # TEST A: JASMY-type (4H Bearish, 1H Bullish, Extremely Weak, Counter Trend)
    test_a = {
        "bias_4h": "BEARISH",
        "bias_1h": "BULLISH",
        "is_counter_trend": True,
        "volume_state": "EXTREMELY_WEAK",
        "volume_risk_status": "BLOCKED",
        "score": 85,
        "core_evidence_pass": True
    }
    print("TEST A Output:", suite.evaluate_trade(test_a))

    # TEST B: PUMP-type (High Score 90 override attempt with Volume Risk Block)
    test_b = {
        "bias_4h": "BEARISH",
        "bias_1h": "BULLISH",
        "is_counter_trend": True,
        "volume_state": "EXTREMELY_WEAK",
        "volume_risk_status": "BLOCKED",
        "score": 90,
        "core_evidence_pass": True
    }
    print("TEST B Output:", suite.evaluate_trade(test_b))

    # TEST C: Same Direction Exception (4H Bearish, 1H Bearish, Extremely Weak Volume)
    test_c = {
        "bias_4h": "BEARISH",
        "bias_1h": "BULLISH", # wait, same direction is bearish / bearish
        "bias_1h": "BEARISH",
        "is_counter_trend": False,
        "volume_state": "EXTREMELY_WEAK",
        "volume_risk_status": "ACCEPTED",
        "valid_ob": True,
        "mss_bos": True,
        "rr_ratio": 1.6,
        "score": 75,
        "core_evidence_pass": True
    }
    print("TEST C Output:", suite.evaluate_trade(test_c))

    # TEST D: Strong Counter Trend
    test_d = {
        "bias_4h": "BEARISH",
        "bias_1h": "BULLISH",
        "is_counter_trend": True,
        "volume_state": "EXTREMELY_WEAK",
        "volume_ risk_status": "ACCEPTED",
        "mss_bos": True,
        "liquidity_sweep": True,
        "strong_displacement": True,
        "valid_ob": True,
        "entry_location": "EXCELLENT",
        "rr_ratio": 2.2,
        "score": 82,
        "core_evidence_pass": True
    }
    print("TEST D Output:", suite.evaluate_trade(test_d))
