"""Hard pre-spend guard. check() runs before EVERY generation call; nothing is spent on a BLOCK."""
from . import config


class BudgetGuard:
    def __init__(self, monthly_recorded_usd, per_listing_limit=config.PER_LISTING_LIMIT_USD, monthly_limit=config.MONTHLY_LIMIT_USD, max_rerolls=config.MAX_REROLLS):
        self.monthly_recorded = round(float(monthly_recorded_usd), 6)
        self.per_listing_limit = per_listing_limit
        self.monthly_limit = monthly_limit
        self.max_rerolls = max_rerolls
        self.job_cost = 0.0
        self.rerolls = 0
        self.usage = []

    def projected(self, next_cost):
        return round(self.job_cost + next_cost, 6), round(self.monthly_recorded + self.job_cost + next_cost, 6)

    def check(self, next_cost):
        job, month = self.projected(next_cost)
        if job > self.per_listing_limit + 1e-9:
            return {"ok": False, "reason": f"next call would bring this campaign to ${job:.4f}, over the ${self.per_listing_limit:.2f} per-listing cap", "projected_job": job, "projected_monthly": month}
        if month > self.monthly_limit + 1e-9:
            return {"ok": False, "reason": f"next call would bring the month to ${month:.4f}, over the ${self.monthly_limit:.2f} monthly cap", "projected_job": job, "projected_monthly": month}
        return {"ok": True, "reason": "", "projected_job": job, "projected_monthly": month}

    def record(self, cost, usage, slot, quality, size, reroll=False, reason=""):
        self.job_cost = round(self.job_cost + cost, 6)
        if reroll:
            self.rerolls += 1
        self.usage.append({"slot": slot, "quality": quality, "size": size, "estimated_cost_usd": cost, "reroll": reroll, "reason": reason, "usage": usage})

    def can_reroll(self):
        return self.rerolls < self.max_rerolls
