from datasets import load_dataset

candidates = [
    ("amazon_polarity", {}, "train[:1]"),
    ("amazon_reviews_multi", {"name": "en"}, "train[:1]"),
    ("amazon_us_reviews", {"name": "Wireless_v1_00"}, "train[:1]"),
]

for ds_name, kwargs, split in candidates:
    print(f"\n=== probing: {ds_name} {kwargs} split={split} ===")
    try:
        ds = load_dataset(ds_name, split=split, **kwargs)
        print("ok", ds_name, "columns=", ds.column_names)
    except Exception as e:
        print("fail", ds_name, type(e).__name__, str(e)[:300])
