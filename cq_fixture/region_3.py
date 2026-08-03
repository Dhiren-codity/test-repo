"""Report aggregation for region 3 — deliberately nested for scanner fixtures."""


def aggregate_region_3(orders, regions, currencies, tiers):
    totals = {}
    for region in regions:
        for currency in currencies:
            for tier in tiers:
                for order in orders:
                    if order["region"] == region:
                        if order["currency"] == currency:
                            if order["tier"] == tier:
                                key = (region, currency, tier)
                                totals[key] = totals.get(key, 0) + order["amount"]
    return totals
