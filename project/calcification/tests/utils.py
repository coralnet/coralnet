from bs4 import BeautifulSoup

from ..models import CalcifyRateTable


def create_global_calcify_table(
        region, rates_dict, name=None, description=None):
    if name is None:
        name = f"Table Name - {region}"
    if description is None:
        description = ""

    table = CalcifyRateTable(
        name=name,
        description=description,
        rates_json=rates_dict,
        source=None,
        region=region,
    )
    table.save()
    return table


def create_source_calcify_table(
        source, rates_dict, name=None, description=None):
    if name is None:
        name = "Table Name"
    if description is None:
        description = ""

    table = CalcifyRateTable(
        name=name,
        description=description,
        rates_json=rates_dict,
        source=source,
        region='',
    )
    table.save()
    return table


def grid_of_tables_html_to_tuples(html):
    """
    This function facilitates checking the grid of tables HTML for the
    expected contents.
    """
    soup = BeautifulSoup(html, 'html.parser')
    data_rows = soup.find_all('tr')[1:]
    tuples = []
    for row in data_rows:
        cells = row.find_all('td')
        tuples.append((
            # Name
            cells[0].text,
            # Description
            cells[1].text,
            # Download/Delete forms
            cells[2].findAll('form')[0].attrs.get('action'),
            cells[2].findAll('form')[1].attrs.get('action'),
        ))
    return tuples
