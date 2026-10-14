"""Business descriptions of the TPC-H schema.

This plays the role of the prototype's Dify knowledge base: text that tells the model what tables and
columns *mean*, which column names alone don't. Retrieval embeds these; the prompt includes them.
"""

from __future__ import annotations

TABLES: dict[str, str] = {
    "region": "The 5 world regions (AFRICA, AMERICA, ASIA, EUROPE, MIDDLE EAST).",
    "nation": "The 25 countries/nations. Each nation belongs to one region. Used to locate customers "
    "and suppliers geographically.",
    "customer": "Customers who place orders: name, address, nation, phone, account balance and market "
    "segment.",
    "supplier": "Suppliers (vendors) who supply parts: name, address, nation, phone, account balance.",
    "part": "The product catalog: parts with name, manufacturer, brand, type, size, container and retail "
    "price.",
    "partsupp": "Which supplier offers which part, with available quantity and the supplier's cost per "
    "unit. Links parts and suppliers (many-to-many).",
    "orders": "Customer orders (order header): customer, status, total price, order date, priority, clerk.",
    "lineitem": "Order lines: each row is one part from one supplier on one order, with quantity, price, "
    "discount, tax, return/line status and ship/commit/receipt dates. Sales revenue, shipping and "
    "returns analysis come from here.",
}

COLUMNS: dict[str, dict[str, str]] = {
    "region": {
        "r_regionkey": "region id (primary key)",
        "r_name": "region name, upper case, e.g. 'EUROPE'",
        "r_comment": "free-text comment",
    },
    "nation": {
        "n_nationkey": "nation id (primary key)",
        "n_name": "nation/country name, upper case, e.g. 'GERMANY', 'UNITED STATES'",
        "n_regionkey": "region of the nation (foreign key to region.r_regionkey)",
        "n_comment": "free-text comment",
    },
    "customer": {
        "c_custkey": "customer id (primary key)",
        "c_name": "customer name, e.g. 'Customer#000000001'",
        "c_address": "street address",
        "c_nationkey": "customer's nation (foreign key to nation.n_nationkey)",
        "c_phone": "phone number; the first two digits are a country code",
        "c_acctbal": "account balance in dollars; can be negative",
        "c_mktsegment": "market segment: AUTOMOBILE, BUILDING, FURNITURE, HOUSEHOLD or MACHINERY",
        "c_comment": "free-text comment",
    },
    "supplier": {
        "s_suppkey": "supplier id (primary key)",
        "s_name": "supplier name, e.g. 'Supplier#000000001'",
        "s_address": "street address",
        "s_nationkey": "supplier's nation (foreign key to nation.n_nationkey)",
        "s_phone": "phone number",
        "s_acctbal": "account balance in dollars; can be negative",
        "s_comment": "free-text comment",
    },
    "part": {
        "p_partkey": "part id (primary key)",
        "p_name": "part name made of color words, e.g. 'goldenrod lavender spring chocolate lace'",
        "p_mfgr": "manufacturer, 'Manufacturer#1' to 'Manufacturer#5'",
        "p_brand": "brand, e.g. 'Brand#13'",
        "p_type": "type: three words, e.g. 'PROMO BURNISHED COPPER' (finish, then material)",
        "p_size": "size, integer 1-50",
        "p_container": "container, e.g. 'SM CASE', 'LG BOX', 'JUMBO PKG'",
        "p_retailprice": "list/retail price per unit in dollars",
        "p_comment": "free-text comment",
    },
    "partsupp": {
        "ps_partkey": "part (foreign key to part.p_partkey)",
        "ps_suppkey": "supplier (foreign key to supplier.s_suppkey)",
        "ps_availqty": "quantity the supplier has available (inventory/stock)",
        "ps_supplycost": "the supplier's cost per unit of the part in dollars",
        "ps_comment": "free-text comment",
    },
    "orders": {
        "o_orderkey": "order id (primary key)",
        "o_custkey": "customer who placed the order (foreign key to customer.c_custkey)",
        "o_orderstatus": "order status: 'F' fulfilled, 'O' open, 'P' partially fulfilled",
        "o_totalprice": "total order price in dollars, including tax and discounts",
        "o_orderdate": "date the order was placed (1992-1998)",
        "o_orderpriority": "priority: '1-URGENT', '2-HIGH', '3-MEDIUM', '4-NOT SPECIFIED', '5-LOW'",
        "o_clerk": "clerk who handled the order, e.g. 'Clerk#000000951'",
        "o_shippriority": "shipping priority (always 0 in generated data)",
        "o_comment": "free-text comment",
    },
    "lineitem": {
        "l_orderkey": "order (foreign key to orders.o_orderkey)",
        "l_partkey": "part sold (foreign key to part.p_partkey)",
        "l_suppkey": "supplier who supplied it (foreign key to supplier.s_suppkey)",
        "l_linenumber": "line number within the order (1-7)",
        "l_quantity": "quantity of units ordered",
        "l_extendedprice": "line price before discount = quantity * part retail price, in dollars",
        "l_discount": "discount as a fraction, 0.00-0.10",
        "l_tax": "tax as a fraction, 0.00-0.08",
        "l_returnflag": "return flag: 'R' returned, 'A' accepted, 'N' not yet known",
        "l_linestatus": "line status: 'O' open, 'F' fulfilled/shipped",
        "l_shipdate": "date the line shipped",
        "l_commitdate": "date the supplier committed to ship/deliver by",
        "l_receiptdate": "date the customer received the item",
        "l_shipinstruct": "shipping instruction, e.g. 'DELIVER IN PERSON', 'TAKE BACK RETURN'",
        "l_shipmode": "shipping mode: AIR, REG AIR, FOB, MAIL, RAIL, SHIP, TRUCK",
        "l_comment": "free-text comment",
    },
}

# (table, column) -> (referenced table, referenced column)
FOREIGN_KEYS: list[tuple[str, str, str, str]] = [
    ("nation", "n_regionkey", "region", "r_regionkey"),
    ("customer", "c_nationkey", "nation", "n_nationkey"),
    ("supplier", "s_nationkey", "nation", "n_nationkey"),
    ("partsupp", "ps_partkey", "part", "p_partkey"),
    ("partsupp", "ps_suppkey", "supplier", "s_suppkey"),
    ("orders", "o_custkey", "customer", "c_custkey"),
    ("lineitem", "l_orderkey", "orders", "o_orderkey"),
    ("lineitem", "l_partkey", "part", "p_partkey"),
    ("lineitem", "l_suppkey", "supplier", "s_suppkey"),
    ("lineitem", "l_partkey", "partsupp", "ps_partkey"),
    ("lineitem", "l_suppkey", "partsupp", "ps_suppkey"),
]
