from datasets import load_dataset

candidates = [
    ("Ha1200/amazon-reviews-sentiment-analysis", {}, "train[:3]"),
    ("SetFit/amazon_reviews_multi_en", {}, "train[:3]"),
    ("juliensimon/amazon-shoe-reviews", {}, "train[:3]"),
    ("saattrupdan/womens-clothing-ecommerce-reviews", {}, "train[:3]"),
    ("m-ric/amazon_product_reviews_datafiniti", {}, "train[:3]"),
]

for ds_name, kwargs, split in candidates:
    print(f"\n=== probing: {ds_name} ===")
    try:
        ds = load_dataset(ds_name, split=split, **kwargs)
        print("ok rows=", len(ds), "columns=", ds.column_names)
    except Exception as e:
        print("fail", type(e).__name__, str(e)[:300])
