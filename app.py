from pathlib import Path
import math

import pandas as pd
import streamlit as st

st.set_page_config(page_title="StockAhead", layout="wide")

DATA = Path(__file__).resolve().parent / "data" / "processed"

@st.cache_data
def load_data():
    history = pd.read_csv(
        DATA / "weekly_history.csv",
        dtype={"StockCode": str},
        parse_dates=["week_start"]
    )
    metrics = pd.read_csv(DATA / "test_metrics.csv")
    scenarios = pd.read_csv(DATA / "inventory_scenarios.csv")
    return history, metrics, scenarios

history, metrics, scenarios = load_data()

product_labels = pd.read_csv(
    DATA / "product_labels.csv",
    dtype={"StockCode": str}
)

product_names = product_labels.set_index("StockCode")[
    "Description"
].to_dict()

test_predictions = pd.read_csv(
    DATA / "test_predictions.csv",
    dtype={"StockCode": str},
    parse_dates=["week_start"]
)

st.title("StockAhead")
st.caption("Retail demand forecasting and inventory planning")
st.info(
    "Historical portfolio prototype. Stock, supplier lead times "
    "and inventory outcomes are simulated."
)

forecast_tab, evaluation_tab, inventory_tab = st.tabs([
    "Replenishment",
    "Forecast evaluation",
    "Inventory scenarios"
])

with forecast_tab:
    product = st.selectbox(
        "Product",
        sorted(history["StockCode"].unique()),
        format_func=lambda code: (
            f"{code} — {product_names.get(code, 'Unknown product')}"
        )
    )

    rows = history.loc[
        history["StockCode"] == product
    ].sort_values("week_start")

    st.subheader("Historical weekly sales")

    st.line_chart(
        rows.set_index("week_start")[["units"]].rename(
            columns={"units": "Actual units sold"}
        )
    )

    st.subheader("Forecasts versus actual sales")
    st.caption(
        "Final 12 test weeks. Each forecast uses information "
        "available before its target week."
    )

    product_test = test_predictions.loc[
        test_predictions["StockCode"] == product
    ].sort_values("week_start")

    comparison_chart = product_test.set_index("week_start")[
        ["units", "last_week", "moving_average_4", "random_forest"]
    ].rename(columns={
        "units": "Actual sales",
        "last_week": "Last week",
        "moving_average_4": "Four-week moving average",
        "random_forest": "Random forest"
    })

    st.line_chart(comparison_chart)

    product_mae = pd.DataFrame([
        {
            "Method": label,
            "MAE in units": (
                product_test["units"] - product_test[column]
            ).abs().mean()
        }
        for column, label in [
            ("last_week", "Last week"),
            ("moving_average_4", "Four-week moving average"),
            ("random_forest", "Random forest")
        ]
    ])

    st.dataframe(product_mae.round(2), hide_index=True)

    method = st.selectbox(
        "Forecast method",
        ["Four-week moving average", "Last week"]
    )

    if method == "Four-week moving average":
        forecast = float(rows["units"].tail(4).mean())
    else:
        forecast = float(rows["units"].iloc[-1])

    next_week = rows["week_start"].max() + pd.Timedelta(weeks=1)
    st.metric("Forecast units", f"{forecast:,.1f}")
    st.caption(
        f"Week starting {next_week:%d %B %Y}. "
        "Uses completed weeks only; the final partial week is excluded."
    )

    col1, col2 = st.columns(2)

    with col1:
        stock = st.number_input(
            "Assumed stock on hand", min_value=0, value=500, step=1
        )
        on_order = st.number_input(
            "Assumed outstanding order units",
            min_value=0, value=0, step=1
        )

    with col2:
        lead_time = st.number_input(
            "Lead time in whole weeks", min_value=1, value=1, step=1
        )
        safety_stock = st.number_input(
            "Safety stock in units", min_value=0, value=100, step=1
        )

    target = math.ceil(forecast * (lead_time + 1) + safety_stock)
    suggested_order = max(0, target - stock - on_order)

    st.metric("Suggested order units", f"{suggested_order:,}")
    st.caption(
        "Target stock = forecast × (lead time + one review week) "
        "+ safety stock. Demand is assumed constant over this period. "
        "Outstanding orders reduce the suggestion; their arrival "
        "timing is not assessed in this calculator."
    )
    st.subheader("Replenishment priorities")
    st.caption(
        "Four-week moving-average forecasts. Edit the simulated "
        "inputs below to compare replenishment needs."
    )

    priority_rows = []

    for code, product_history in history.groupby("StockCode"):
        product_history = product_history.sort_values("week_start")
        prediction = float(product_history["units"].tail(4).mean())

        priority_rows.append({
            "Product": code,
            "Forecast units": prediction,
            "Stock on hand": 500,
            "Lead time weeks": 1,
            "Safety stock units": 100
        })

        saved_inputs_path = DATA / "priority_inputs.csv"

    if "priority_base" not in st.session_state:
        base = pd.DataFrame(priority_rows)

        if saved_inputs_path.exists():
            saved = pd.read_csv(
                saved_inputs_path,
                dtype={"Product": str}
            )

            editable_columns = [
                "Stock on hand",
                "Lead time weeks",
                "Safety stock units"
            ]

            saved = saved.set_index("Product")

            for column in editable_columns:
                base[column] = (
                    base["Product"].map(saved[column])
                    .fillna(base[column])
                    .astype(int)
                )

        st.session_state["priority_base"] = base

        editor_data = st.session_state["priority_base"].copy()

    editor_data.insert(
        1,
        "Product name",
        editor_data["Product"].map(product_names).fillna("Unknown product")
    )

    inputs = st.data_editor(
        editor_data,
        disabled=["Product", "Forecast units"],
        column_config={
            "Stock on hand": st.column_config.NumberColumn(
                min_value=0, step=1
            ),
            "Lead time weeks": st.column_config.NumberColumn(
                min_value=1, step=1
            ),
            "Safety stock units": st.column_config.NumberColumn(
                min_value=0, step=1
            )
        },
        hide_index=True,
        key="priority_inputs"
    )

    if st.button("Save scenario inputs", key="save_priority_inputs"):
        inputs[
            [
                "Product",
                "Stock on hand",
                "Lead time weeks",
                "Safety stock units"
            ]
        ].to_csv(saved_inputs_path, index=False)

        st.success("Inputs saved. They will survive a browser refresh.")

    priorities = inputs.copy()


    priorities["Target stock"] = priorities.apply(
        lambda row: math.ceil(
            row["Forecast units"] * (row["Lead time weeks"] + 1)
            + row["Safety stock units"]
        ),
        axis=1
    )

    priorities["Suggested order"] = (
        priorities["Target stock"] - priorities["Stock on hand"]
    ).clip(lower=0).astype(int)

    priorities["Projected next-week shortage"] = (
        priorities["Forecast units"] - priorities["Stock on hand"]
    ).clip(lower=0).apply(math.ceil)

    priorities = priorities.sort_values(
        ["Projected next-week shortage", "Suggested order"],
        ascending=[False, False]
    )

    st.subheader("Products to review first")
    st.dataframe(
        priorities.round({"Forecast units": 1}),
        hide_index=True
    )

    st.caption(
        "Ranks products by projected next-week shortage, then "
        "suggested order quantity. Assumes no outstanding orders. "
        "An order placed now cannot prevent a shortage before it arrives."
    )

    st.divider()
    st.subheader("Product detail")

with evaluation_tab:
    st.subheader("Final chronological test results")
    st.dataframe(metrics.round(2), hide_index=True, use_container_width=True)
    st.write(
        "The moving average achieved the lowest overall test MAE. "
        "Random forest won for 9 products, moving average for 10, "
        "and last week for 1."
    )

with inventory_tab:
    st.subheader("Historical inventory simulation")
    st.caption(
        "One-week lead time; initial stock equals two weeks of "
        "average training sales. Buffers also use training averages. "
        "Unfulfilled demand is treated as lost sales."
    )

    buffer = st.select_slider(
        "Safety-stock buffer in weeks",
        options=[0.0, 0.5, 1.0, 2.0],
        value=0.5
    )

    selected = scenarios.loc[
        scenarios["safety_stock_weeks"] == buffer
    ]

    st.dataframe(
        selected.round(2), hide_index=True, use_container_width=True
    )
    st.caption(
        "These are exploratory scenarios on historical test weeks. "
        "Recorded sales serve as simulated demand; actual stockouts "
        "and unmet customer demand are unknown."
    )