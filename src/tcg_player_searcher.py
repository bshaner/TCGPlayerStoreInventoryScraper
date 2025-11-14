import getopt
import pandas as pd
import re
import sys
import time
from datetime import date
from enum import Enum
from types import DynamicClassAttribute


from scrape import scrape_store_by_sets

# Excel format globals
INVENTORY_SHEET_NAME = "Store Inventory"
DESIRED_CARDS_SHEET_NAME = "Wanted Cards"

# Globals for dataframes
class InventoryColumn(Enum):
    NAME = 0
    TREATMENT = 1
    NAME_WITHOUT_TREATMENT = 2
    SET = 3
    RARITY = 4
    QUANTITY = 5
    CONDITION_LANGUAGE = 6
    PRICE = 7
    IMAGE_URL = 8
    PRODUCT_URL = 9

    @DynamicClassAttribute
    def name(self):
        name = super(InventoryColumn, self).name
        return name.replace("_", " ").title()

class DesiredCardsColumn(Enum):
    QUANTITY = 0
    NAME = 1
    SET_CODE = 2
    SET_NUMBER = 3
    TREATMENT = 4
    MARKET_PRICE = 5
    CONDITION_LANGUAGE = 6
    PRICE = 7
    PRODUCT_URL = 8

    @DynamicClassAttribute
    def name(self):
        name = super(DesiredCardsColumn, self).name
        return name.replace("_", " ").title()

INVENTORY_HEADER = [column.name for column in InventoryColumn]
DESIRED_CARDS_HEADER = [column.name for column in DesiredCardsColumn]


def load_desired_cards_from_file(file_location):
    """Attempts to load the desired cards to search against store inventory from a txt file in Moxfield format".
       Set code and set number are both optional, but will be used to find an exact match when provided.
       Foiling indicator is ignored.

    Args:
        file_location (string): file_location for wanted cards text file. 

    Returns:
        list: list of desired cards with quantity and name as fields.
    """

    desired_cards = []

    if not file_location:
        return desired_cards

    try:
        with open(file_location, "r") as f:
            file_content = f.read()

        if not file_content:
            print("no data found in file " + file_location)
            return desired_cards
        
        # format in file is {qty} {card name}
        cards = file_content.splitlines()
        for card in cards:
            # Set number for The List will prefix the original set code like "(PLST) EMA-76"
            # Set number may indicate a prerelease card like "(PDSK) 23p"
            # Set number from Unstable may have a variant letter like "(UST) 82c"
            #           {qty}    {name} {set code}   {set number}             {foiling}
            pattern = r"([0-9]+) (.*?)(?: \((\w+)\) ?((?:\w+-)?[0-9]+[a-z]?))?(?: \*F\*)?\s*$"
            desired_card = re.findall(pattern, card)
            if desired_card:
                desired_cards.append(desired_card[0])

        return desired_cards

    except Exception as e:
        print("Failed to load desired cards from file " + file_location)
        print(e)
        exit(4)


def column(matrix, column_index):
    """Returns the column from the matrix based on the supplied column_index

    Args:
        column_index (int): index (zero based) of the column to retrieve.

    Returns:
        list: rows for the given column index.
    """

    return [row[column_index] for row in matrix]


def find_wanted_cards_dataframe(store_card_inventory, wanted_cards):
    """Returns a dataframe represented a filtered list of the supplied store_card_inventory list based on the wanted_cards name.

    Args:
        store_card_inventory (list): list of store card inventory to search wanted_cards against
        wanted_cards (list): list of card names to search store_card_inventory against

    Returns:
        dataframe: dataframe based on matched wanted_cards
    """

    # let's use pandas to grab rows from scraped site so that all of the columns are visible so users can quickly see things like price, condition, etc. instead of just card name
    wanted_card_names = column(wanted_cards, 1)

    # Get dataframe to query against
    cards_df = pd.DataFrame(data = store_card_inventory, columns = INVENTORY_HEADER)
    found_cards_df = cards_df[cards_df[InventoryColumn.NAME.name].isin(wanted_card_names)]

    # TODO: Restrict match by set code if provided
    # TODO: Restrict match by prerelease/set number if provided
    # TODO: Restrict match by foiling if provided

    return found_cards_df


def extract_store_name(store_url, cached_results_file):
    """Extracts the store name from either the store_url or cached_results_file

    Args:
        store_url (string): URL of the TCGPlayer Pro store
        cached_results_file (string): file name of cached results file

    Returns:
        string: extracted store name
    """

    store_name = ""
    if store_url:
        pattern = r"(?:https?://)?([^.]+)(?:\.tcgplayerpro\.com)/?"
        match = re.match(pattern, store_url)
        if match:
            store_name = match.group(1)
    elif cached_results_file:
        pattern = r"([^-]+)(?:-[^\.]+\.xlsx)/?"
        match = re.match(pattern, cached_results_file)
        if match:
            store_name =  match.group(1)

    return store_name


def write_inventory_to_excel(store_card_inventory, store_name):
    """Writes the store_card_inventory list to an Excel file

    Args:
        store_card_inventory (list): scraped store_card_inventory list
        store_name (string): name of the store
    """

    cards_df = pd.DataFrame(data = store_card_inventory, columns = INVENTORY_HEADER)
 
    writer = pd.ExcelWriter(store_name + "-" + str(date.today()) + ".xlsx", engine = "xlsxwriter", engine_kwargs={"options": {"strings_to_urls": False}})

    cards_df.to_excel(writer, index=False, sheet_name = INVENTORY_SHEET_NAME)
    
    writer.close()


def add_inventory_details_to_wanted_card(wanted_card, found_cards_df):
    """Adds inventory details from found_cards_df to the wanted_card list

    Args:
        wanted_card (list): list representing a wanted card
        found_cards_df (dataframe): data frame of found cards, most likely from find_wanted_cards_dataframe
        
    Returns:
        tuple: updated wanted_card list with inventory details appended
    """
    matching_cards = found_cards_df[found_cards_df[InventoryColumn.NAME.name] == wanted_card[DesiredCardsColumn.NAME.value]]
    if matching_cards.empty:
        return wanted_card
    
    # Choose card with lowest price, then best condition
    low_price_matches = matching_cards[matching_cards[InventoryColumn.PRICE.name] == matching_cards[InventoryColumn.PRICE.name].min()]
    # TODO: pick best condition instead of first available, need to parse out conditions and order
    best_match = low_price_matches.iloc[0]

    treatment = best_match[InventoryColumn.TREATMENT.name]
    market_price = 0  # TODO: placeholder for market price
    condition = best_match[InventoryColumn.CONDITION_LANGUAGE.name]
    price = best_match[InventoryColumn.PRICE.name]
    url = best_match[InventoryColumn.PRODUCT_URL.name]

    return wanted_card + (treatment, market_price, condition, price, url)



def write_search_results_to_excel(store_card_inventory, wanted_cards, found_cards_df, store_name):
    """Writes a filtered store_card_inventory list, wanted_cards list, and found_cards_df dataframe to an Excel file

    Args:
        store_card_inventory (list): scraped store_card_inventory list
        wanted_cards (list): list of wanted cards
        found_cards_df (dataframe): data frame of found cards, most likely from find_wanted_cards_dataframe
        store_name (string): name of the store
    """

    filtered_inventory = [item for item in store_card_inventory if item[InventoryColumn.NAME.value] in found_cards_df[InventoryColumn.NAME.name].values]
    filtered_inventory.sort()

    wanted_cards_detail = [add_inventory_details_to_wanted_card(card, found_cards_df) for card in wanted_cards]
    wanted_cards_df = pd.DataFrame(data = wanted_cards_detail, columns = DESIRED_CARDS_HEADER)

    # TODO: add lowest available price from store for each wanted card
    # TODO: add TCGPlayer market price for each wanted card
    cards_df = pd.DataFrame(data = filtered_inventory, columns = INVENTORY_HEADER)
 
    writer = pd.ExcelWriter(store_name + "-" + str(date.today()) + ".results.xlsx", engine = "xlsxwriter", engine_kwargs={"options": {"strings_to_urls": False}})

    cards_df.to_excel(writer, index=False, sheet_name = INVENTORY_SHEET_NAME)
    wanted_cards_df.to_excel(writer, index=False, sheet_name = DESIRED_CARDS_SHEET_NAME)
    
    writer.close()
    

def load_cached_store_results(file_location):
    """Loads cached store results from an Excel file.

    Args:
        file_location (string): file location of the cached results Excel file.

    Returns:
        list: list of store card inventory from cached results.
    """

    store_card_inventory = []

    try:
        df = pd.read_excel(file_location, sheet_name=INVENTORY_SHEET_NAME)
        store_card_inventory = df.values.tolist()
        return store_card_inventory
    except Exception as e:
        print("Failed to load cached store results from " + file_location)
        print(e)
        exit(3)


def main(argv):
    # defaults
    headless = False
    store_url = ""
    buylist_location = ""
    cached_results = ""

    try:
        opts, args = getopt.getopt(argv,"u:b:c:",["store-url=","buylist=","cached-results=","headless"])
    except getopt.GetoptError:
        print('tcg_player_searcher.py -u <store-url> [-b <buylist> -c <cached-results>]')
        print("\tstore-url is the TCGPlayer Pro store URL. Ex) https://examplestore.tcgplayerpro.com/")
        # TODO: allow multiple store URLs
        print("\tbuylist is the optional file location for a list of card names (in a text file) that you're looking to find.")
        print("\tcached-results is an optional file location for previously scraped store results to use instead of scraping the store live")
        # TODO: cache results in a directory so we can find them automatically by store name?
        # TODO: add argument for minimum card condition
        print("\theadless is an optional flag to run the scraper in headless mode")
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-u", "--store-url"):
            store_url = arg      
        if opt in ("-b", "--buylist"):
            buylist_location = arg
        if opt in ("-c", "--cached-results"):
            cached_results = arg
        if opt in ("--headless"):
            headless = True

    # Store name is mandatory
    if not store_url and not cached_results:
        print("Please provide store URL or cached results file. Exiting.")
        sys.exit(2)

    desired_cards = []
    if buylist_location:
        desired_cards = load_desired_cards_from_file(buylist_location)

    store_name = extract_store_name(store_url, cached_results)


    print("Store Name: " +  store_name)
    print("Store URL: " + store_url)
    print("Total desired cards to search for: " + str(len(desired_cards)))

    start = time.time()

    if cached_results:
        store_card_inventory = load_cached_store_results(cached_results)
    else:
        store_card_inventory = scrape_store_by_sets(store_url, headless)
        write_inventory_to_excel(store_card_inventory, store_name)

    found_cards_in_inventory_df = find_wanted_cards_dataframe(store_card_inventory, desired_cards)
    write_search_results_to_excel(store_card_inventory, desired_cards, found_cards_in_inventory_df, store_name)

    end = time.time()
    elapsed_time = end - start
    total_cards_scraped = len(store_card_inventory)
    cards_scraped_per_second = total_cards_scraped / elapsed_time

    print("Script run time: " + str(elapsed_time))
    print("Total cards in inventory: " + str(total_cards_scraped))
    if not cached_results:
        print("Cards scraped per second: " + str(cards_scraped_per_second))
    len(set(found_cards_in_inventory_df[InventoryColumn.NAME.name]))
    print("Desired cards found: " + str(len(set(found_cards_in_inventory_df[InventoryColumn.NAME.name]))))


if __name__ == "__main__":
    main(sys.argv[1:])
