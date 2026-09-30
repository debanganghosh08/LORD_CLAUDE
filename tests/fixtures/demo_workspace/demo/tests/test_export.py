def test_monthly_csv_has_header_and_rows(services):
    csv_text = services.export.monthly_csv(2026, 3)
    lines = csv_text.splitlines()
    assert lines[0] == "date,kind,category,description,amount"
    assert lines[1] == "2026-03-02,expense,rent,Rent March,650.00"
    assert len(lines) == 5
