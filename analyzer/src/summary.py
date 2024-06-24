import duckdb

TIMESTAMP_FORMAT = '%xT%X.%g%z'


def exceed_cap_count(db, delta_pct=10):
    delta_ratio = 1 + delta_pct / 100
    base_sql = 'select count(*) from bmc where power / cap_level '
    all_sql = base_sql + '> 1'
    threshold_sql = base_sql + f'>= {delta_ratio}'
    all_excess = db.execute(all_sql).fetchone()[0]
    threshold_excess = db.execute(threshold_sql).fetchone()[0]

    return all_excess, threshold_excess


def create_views(db):
    bmc_v_sql = f"create view bmc_v as select strptime(timestamp, '{TIMESTAMP_FORMAT}') as timestamp, power, cap_level from bmc;"
    rapl_v_sql = f"create view bmc_v as select strptime(timestamp, '{TIMESTAMP_FORMAT}') as timestamp, power, cap_level from bmc;"


if __name__ == '__main__':
    db_path = '../data/oahu10015_240624_capping_test.db'
    threshold_ratio = 1.2
    threshold_pct = (threshold_ratio - 1) * 100
    with duckdb.connect(db_path) as db:
        create_views(db)
        print(f'Number of samples where power > cap: {exceed_cap_count(db)[0]}')
        print(f'Number of samples where power/cap ≥ {threshold_ratio}: {exceed_cap_count(db, threshold_pct)[1]}')
