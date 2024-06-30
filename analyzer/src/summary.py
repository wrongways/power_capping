"""summary.py - presents the capping tool results.

It loads a test run’s sqlite3 database and presents interactive
plots from a web server running on http://localhost:8050
"""

import sqlite3
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html, Input, Output
from plotly import express as px


def exceed_cap_count(db, delta_pct=10):
    """Count the number of samples where the BMC power exceeds the BMC cap.

    @param db: an open connection to the sqlite3 database
    @param delta_pct:  the percentage equal or above which to count excess samples.
    @return the count of samples exceeding the threshold percentage
    """
    delta_ratio = 1 + delta_pct / 100
    base_sql = 'select count(*) from bmc where power / cap_level '
    all_sql = base_sql + '> 1'
    threshold_sql = base_sql + f'>= {delta_ratio}'
    all_excess = db.execute(all_sql).fetchone()[0]
    threshold_excess = db.execute(threshold_sql).fetchone()[0]

    return all_excess, threshold_excess


def test_duration(db):
    """Returns the total test duration."""
    sql = 'select min(start_time) as start_time, max(end_time) as end_time from tests;'
    start_time, end_time = db.execute(sql).fetchone()
    datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)


def load_plot_data(cap_up_down, with_pause, stepped, load_pct):
    """Loads plot data from sqlite3 database.

    @param cap_up_down: the capping direction to load, this is either '>' or '<'
    @param with_pause: boolean to plot data for test cases that pause between capping commands
    @param stepped: boolean to plot data that decrease progressively or in a single shot
    @param load_pct: the percentage firestarter load to display

    @return None
    """
    tests_sql = (f"select start_time, end_time from tests where "
                 f"cap_from {cap_up_down} cap_to and "
                 f"pause_load_between_cap_settings = {with_pause} and "
                 f"load_pct = {load_pct} and "
                 f"n_steps {'>' if stepped else '='} 1 "
                 "order by start_time;")

    print(tests_sql)
    bmc_sql_root = "select timestamp, power, cap_level from bmc where timestamp "
    rapl_sql_root = "select timestamp, power, package from rapl where timestamp "
    capping_sql_root = "select timestamp, cap_level from capping_commands where timestamp "

    with sqlite3.connect(db_path, uri=True) as db:
        start_time, end_time = db.execute(tests_sql).fetchone()
        print("Start time:", start_time)

        interval = f"between '{start_time}' and '{end_time}'"
        bmc_sql = bmc_sql_root + interval
        rapl_sql = rapl_sql_root + interval
        capping_sql = capping_sql_root + interval

        start_time = datetime.fromisoformat(start_time)
        print(f'{start_time=}')

        print(bmc_sql)
        print(rapl_sql)

        bmc_power = [
            {
                'timestamp': (datetime.fromisoformat(b[0]) - start_time).total_seconds(),
                'power': b[1],
                'package': 'bmc'
            } for b in db.execute(bmc_sql).fetchall()
        ]

        bmc_cap_level = [
            {
                'timestamp': (datetime.fromisoformat(b[0]) - start_time).total_seconds(),
                'power': b[2],
                'package': 'bmc_cap_level'
            } for b in db.execute(bmc_sql).fetchall()
        ]

        rapl_power = [
            {
                'timestamp': (datetime.fromisoformat(r[0]) - start_time).total_seconds(),
                'power': r[1],
                'package': r[2]
            } for r in db.execute(rapl_sql).fetchall()
        ]

        capping_orders = [
            {
                'timestamp': (datetime.fromisoformat(r[0]) - start_time).total_seconds(),
                'power': r[1],
                'package': 'capping_order'
            } for r in db.execute(capping_sql).fetchall()
        ]

    return pd.DataFrame(bmc_power + bmc_cap_level + rapl_power + capping_orders)


def make_graph(cap_up_down, pause, stepped, load_pct):
    """Create plotly express graph."""
    graph_df = load_plot_data(cap_up_down, pause, stepped, load_pct)

    print(graph_df)

    return px.line(graph_df, x='timestamp', y='power', color='package')


app = dash.Dash(external_stylesheets=[dbc.themes.FLATLY], title="Capping Results")


def create_selector_buttons():
    """Create the dash bootstrap selector buttons.

    The buttons are created dynamically from data in the database content
    and are used to select the data to plot
    """
    with sqlite3.connect(db_path, uri=True) as db:
        load_percentages = [
            pct[0] for pct in db.execute('select distinct load_pct from tests').fetchall()
        ]

    return dbc.Row(children=[
        dbc.Label(html_for='cap_up_down', children='Cap Direction'),
        dbc.RadioItems(
                id='cap_up_down',
                className='btn-group',
                inputClassName='btn-check',
                labelClassName='btn btn-outline-primary',
                options=[
                    # The values of this field are used in the SQL select
                    {'label': 'High to low', 'value': '>'},
                    {'label': 'Low to high', 'value': '<'}
                ],
                value='>',
        ),
        dbc.Label(html_for='pause', children='Pause before cap operation'),
        dbc.RadioItems(
                id='pause',
                className='btn-group',
                inputClassName='btn-check',
                labelClassName='btn btn-outline-primary',
                options=[
                    {'label': 'Yes', 'value': True},
                    {'label': 'No ', 'value': False}
                ],
                value=False,
        ),
        dbc.Label(html_for='stepped', children='Cap stepped or one-shot'),
        dbc.RadioItems(
                id='stepped',
                className='btn-group',
                inputClassName='btn-check',
                labelClassName='btn btn-outline-primary',
                options=[
                    {'label': 'Stepped', 'value': True},
                    {'label': 'One shot ', 'value': False}
                ],
                value=False,
        ),

        dbc.Label(html_for='load_pct', children='Load percent'),
        dbc.RadioItems(
                id='load_pct',
                className='btn-group',
                inputClassName='btn-check',
                labelClassName='btn btn-outline-primary',
                options=[
                    {'label': f'{v:3d}%', 'value': v} for v in load_percentages
                ],
                value=load_percentages[0]),
    ],
            className='radio-group'
    )


def get_system_info():
    """Retrieve system information

    @return system hostname, os_name, # cpus
    """

    sql = 'select hostname, os_name, cpus from system_info'
    with sqlite3.connect(db_path, uri=True) as db:
        hostname, os_name, cpus = db.execute(sql).fetchone()
        return hostname, os_name, cpus


def main_page_layout():
    """Create the plotly layout.

    Using dash bootstrap components
    """
    return dbc.Container([
        html.H2('Capping results'),
        create_selector_buttons(),
        html.H2('System information'),
        html.P("", id='system-info'),
        dcc.Graph(id='plot')
    ])


if __name__ == '__main__':
    import argparse


    def parse_args():
        """Parse CLI arguments."""
        parser = argparse.ArgumentParser(
                prog='Capping analyzer',
                description='Plotting interface for capping tool results',
        )
        parser.add_argument('-d', '--db_path', required=True,
                            help='Path to the sqlite3 database file containing the test run samples')

        return parser.parse_args()


    args = parse_args()
    print(args)
    db_path = f'file:{args.db_path}?mode=ro'

    threshold_ratio = 1.2
    threshold_pct = int((threshold_ratio - 1) * 100)
    with sqlite3.connect(db_path, uri=True) as conn:
        # Display some preliminary statistics.
        print(f'Number of samples where power > cap: {exceed_cap_count(conn)[0]}')
        print(f'Number of samples where power/cap ≥ {threshold_ratio}: '
              f'{exceed_cap_count(conn, threshold_pct)[1]}')
        test_duration(conn)

    app.layout = main_page_layout()


    @app.callback(
            Output(component_id='system-info', component_property='children'),
            Output(component_id='plot', component_property='figure'),
            Input(component_id='cap_up_down', component_property='value'),
            Input(component_id='pause', component_property='value'),
            Input(component_id='stepped', component_property='value'),
            Input(component_id='load_pct', component_property='value')
    )
    def get_results(cap_up_down, pause, stepped, load_pct):
        """The plotly callback for the graph.

        @param cap_up_down: direction of capping operation '<' or '>'
        @param pause: pause load between capping operations
        @param stepped: progressive change in cap-level or one-shot
        @param load_pct: firestarter load

        @return The system info paragraph and updated plot.
        """
        hostname, os_name, cpus = get_system_info()
        system_info = f'System: {hostname} ({os_name}): {cpus} CPUs'

        graph = make_graph(cap_up_down, pause, stepped, load_pct)
        return system_info, graph


    app.run_server(debug=True)
