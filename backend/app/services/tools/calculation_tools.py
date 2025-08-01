import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import statistics

class PerformanceCalculationTools:
    """실적 분석 계산 도구 클래스"""
    
    @staticmethod
    def calculate_achievement_rate(performance: float, target: float) -> Dict[str, Any]:
        """달성률을 계산합니다."""
        if target <= 0:
            return {
                "achievement_rate": 0.0,
                "gap_amount": float(performance),
                "evaluation": "목표 없음"
            }
        
        achievement_rate = (performance / target) * 100
        gap_amount = performance - target
        
        if achievement_rate >= 120:
            evaluation = "매우 우수"
        elif achievement_rate >= 100:
            evaluation = "우수"
        elif achievement_rate >= 80:
            evaluation = "양호"
        elif achievement_rate >= 60:
            evaluation = "보통"
        else:
            evaluation = "개선 필요"
        
        return {
            "achievement_rate": float(achievement_rate),  # numpy 타입 방지
            "gap_amount": float(gap_amount),
            "evaluation": evaluation
        }
    
    @staticmethod
    def calculate_enhanced_trend_analysis(amounts: List[float]) -> Dict[str, Any]:
        """트렌드 분석"""
        if len(amounts) < 2:
            return {
                "trend": "데이터 부족",
                "trend_strength": "없음",
                "r_squared": 0.0,
                "slope": 0.0,
                "mean": 0.0,
                "stability": "분석 불가",
                "coefficient_of_variation": 0.0,
                "std_deviation": 0.0,
                "analysis": "분석에 필요한 데이터가 부족합니다."
            }
        
        try:
            # 선형 회귀 분석
            x = np.arange(len(amounts))
            y = np.array(amounts)
            
            # 기본 통계
            n = len(amounts)
            x_mean = np.mean(x)
            y_mean = np.mean(y)
            
            # 기울기와 절편 계산
            numerator = np.sum((x - x_mean) * (y - y_mean))
            denominator = np.sum((x - x_mean) ** 2)
            
            if denominator == 0:
                slope = 0
            else:
                slope = numerator / denominator
            
            intercept = y_mean - slope * x_mean
            
            # R² 계산
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - y_mean) ** 2)
            
            if float(ss_tot) == 0:
                r_squared = 1.0 if float(ss_res) == 0 else 0.0
            else:
                r_squared = 1 - (ss_res / ss_tot)
            
            # 트렌드 분류
            slope_val = float(slope)
            y_mean_val = float(y_mean)
            
            if abs(slope_val) < y_mean_val * 0.01:  # 평균의 1% 미만
                trend = "안정"
                trend_strength = "낮음"
            elif slope_val > y_mean_val * 0.05:  # 평균의 5% 이상 증가
                trend = "강한 상승"
                trend_strength = "높음"
            elif slope_val > 0:
                trend = "상승"
                trend_strength = "보통"
            elif slope_val < -y_mean_val * 0.05:  # 평균의 5% 이상 감소
                trend = "강한 하락"
                trend_strength = "높음"
            else:
                trend = "하락"
                trend_strength = "보통"
            
            # 안정성 분석 (분산 분석 통합)
            amounts_array = np.array(amounts)
            mean_val = float(np.mean(amounts_array))
            std_dev = float(np.std(amounts_array))
            cv = (std_dev / mean_val) * 100 if mean_val > 0 else 0.0
            
            # 안정성 평가
            if cv < 10:
                stability = "매우 안정"
            elif cv < 20:
                stability = "안정"
            elif cv < 30:
                stability = "보통"
            elif cv < 50:
                stability = "불안정"
            else:
                stability = "매우 불안정"
            
            return {
                "trend": trend,
                "trend_strength": trend_strength,
                "r_squared": float(r_squared),
                "slope": float(slope),
                "intercept": float(intercept),
                "mean": mean_val,
                "stability": stability,
                "coefficient_of_variation": float(cv),
                "std_deviation": std_dev,
                "analysis": f"{trend} 트렌드, 변동성 {cv:.1f}% ({stability})"
            }
            
        except Exception as e:
            return {
                "trend": "분석 실패",
                "trend_strength": "없음",
                "r_squared": 0.0,
                "slope": 0.0,
                "mean": 0.0,
                "stability": "분석 불가",
                "coefficient_of_variation": 0.0,
                "std_deviation": 0.0,
                "analysis": f"트렌드 분석 중 오류: {e}"
            }
    
    @staticmethod
    def calculate_seasonal_analysis(monthly_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """계절성 분석 계산"""
        if len(monthly_data) < 4:
            return {
                "has_seasonality": False,
                "peak_months": [],
                "low_months": [],
                "seasonal_factor": {},
                "seasonality_strength": "없음"
            }
        
        # 월별 평균 계산
        month_totals = {}
        for data in monthly_data:
            month = data["month"][-2:]  # YYYYMM에서 MM 추출
            amount = data["amount"]
            
            if month not in month_totals:
                month_totals[month] = []
            month_totals[month].append(amount)
        
        # 각 월의 평균 계산
        month_averages = {}
        for month, amounts in month_totals.items():
            month_averages[month] = float(np.mean(amounts))
        
        if len(month_averages) < 2:
            return {
                "has_seasonality": False,
                "peak_months": [],
                "low_months": [],
                "seasonal_factor": {},
                "seasonality_strength": "없음"
            }
        
        overall_average = float(np.mean(list(month_averages.values())))
        
        # 계절성 지수 계산
        seasonal_factors = {}
        for month, avg in month_averages.items():
            seasonal_factors[month] = float(avg / overall_average)
        
        # 피크와 저점 월 찾기
        sorted_months = sorted(month_averages.items(), key=lambda x: x[1], reverse=True)
        peak_months = [month for month, _ in sorted_months[:2]]
        low_months = [month for month, _ in sorted_months[-2:]]
        
        # 계절성 존재 여부 판단 (최고와 최저의 차이가 평균의 20% 이상)
        max_avg = float(max(month_averages.values()))
        min_avg = float(min(month_averages.values()))
        has_seasonality = bool((max_avg - min_avg) / overall_average > 0.2)
        
        # seasonality_strength 계산
        strength_ratio = (max_avg - min_avg) / overall_average
        if strength_ratio > 0.5:
            seasonality_strength = "강함"
        elif strength_ratio > 0.2:
            seasonality_strength = "보통"
        else:
            seasonality_strength = "약함"
        
        return {
            "has_seasonality": has_seasonality,
            "peak_months": peak_months,
            "low_months": low_months,
            "seasonal_factor": {k: float(round(v, 3)) for k, v in seasonal_factors.items()},
            "seasonality_strength": seasonality_strength
        } 