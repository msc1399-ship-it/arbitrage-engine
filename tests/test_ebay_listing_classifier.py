import pytest

from services.ebay_listing_classifier import classify_ebay_listing, normalized_condition


def classify(title):
    return classify_ebay_listing(
        {"title": title},
        set_num="10295-1",
        expected_terms=("Porsche 911", "911 Turbo", "911 Targa"),
    ).category


@pytest.mark.parametrize("title", [
    "LEGO Icons 10295 Porsche 911 Turbo/Targa",
    "LEGO 10295 Porsche 911 Set con embalaje original e instrucciones",
    "LEGO Porsche 911 10295 set completo 1458 piezas",
])
def test_complete_sets_are_not_rejected_for_instructions_or_piece_count(title):
    assert classify(title) == "FULL_SET"


@pytest.mark.parametrize("title", [
    "Juego de luces LED para LEGO Porsche 911 10295",
    "Placa de matricula LEGO 10295 Porsche 911",
    "Supporto Display compatibile con LEGO Porsche 911 10295",
    "Cerchi Fuchs realistici compatibili con LEGO 10295 Porsche 911",
    "Porsche 911 10295 soporte de pared LEGO impreso 3D",
    "Teca in plexiglass showcase per set LEGO 10295 Porsche 911",
])
def test_accessories_do_not_enter_full_set_distribution(title):
    assert classify(title) == "ACCESSORY"


def test_multiple_sets_are_not_treated_as_one_full_set():
    assert classify(
        "3 LEGO Icons 10300 DeLorean 10321 Corvette 10295 Porsche 911"
    ) == "OTHER"


def test_incomplete_percentage_is_detected():
    assert classify("LEGO 10295 Porsche 911 Turbo Targa 97% completo") == "INCOMPLETE_SET"


def test_alternate_build_is_compatible_product():
    assert classify(
        "LEGO 10295 Porsche 911 Lamborghini Countach alternative model"
    ) == "COMPATIBLE_PRODUCT"


def test_moc_with_punctuation_is_compatible_product():
    assert classify("LEGO Porsche 911 Gulf MOC, Set 10295") == "COMPATIBLE_PRODUCT"


@pytest.mark.parametrize("title,expected", [
    ("LEGO Porsche 911 10295 (SOLO MANUAL)", "INSTRUCTIONS"),
    ("LEGO Porsche 911 10295 MANUAL SOLO SIN Ladrillos", "INSTRUCTIONS"),
    ("LEGO Porsche 911 10295 folleto de instrucciones solo", "INSTRUCTIONS"),
    ("LEGO repuesto Porsche 911 10295 bolsa 10", "PARTS"),
    ("LEGO 10295 Porsche 911 Targa solo piezas impresas", "PARTS"),
    ("LEGO Porsche 911 10295 Manual + Bolsa sellada 10 piezas", "PARTS"),
    ("LEGO 21318 Treehouse 434 Pg. Assembly Manual Book Only", "INSTRUCTIONS"),
    ("LEGO Porsche 911 10295 casi completo", "INCOMPLETE_SET"),
    ("LEGO Porsche 911 10295 completitud desconocida", "INCOMPLETE_SET"),
    ("LEGO 10300 Regreso al Futuro Piezas Faltantes Incompletas", "INCOMPLETE_SET"),
])
def test_manual_and_replacement_variants_are_filtered(title, expected):
    assert classify(title) == expected


def test_exact_number_without_brand_is_uncertain():
    assert classify("Porsche 911 10295 100% completo") == "UNCERTAIN"


def test_full_rebrickable_name_matches_title_tokens_not_literal_phrase():
    result = classify_ebay_listing(
        {"title": "LEGO Icons 10295 Porsche 911 Turbo o Targa nuevo"},
        set_num="10295-1",
        expected_terms=("Porsche 911 Turbo & 911 Targa",),
    )
    assert result.category == "FULL_SET"


@pytest.mark.parametrize("title,set_num,name", [
    ("LEGO Star Wars R2D2 75308 nuevo sellado", "75308-1", "R2-D2"),
    ("LEGO Ideas Casa del Arbol 21318 nuevo", "21318-1", "Tree House"),
    ("LEGO 10300 Regreso al Futuro Maquina del Tiempo nuevo", "10300-1",
     "Back to the Future Time Machine"),
])
def test_identity_variants_can_use_canonical_or_full_set_signals(title, set_num, name):
    result = classify_ebay_listing(
        {"title": title}, set_num=set_num, expected_terms=(name,)
    )
    assert result.category == "FULL_SET"


@pytest.mark.parametrize("title,set_num,expected", [
    ("Marco en la pared para LEGO Lamborghini Sian 42115", "42115-1", "ACCESSORY"),
    ("Kit de iluminacion LED Briksmax para LEGO 10300", "10300-1", "ACCESSORY"),
    ("LEGO 10300 bolsa sellada #7", "10300-1", "PARTS"),
    ("LEGO 42115 libros de instrucciones de construccion", "42115-1", "INSTRUCTIONS"),
    ("2x LEGO 10300 Back to the Future nuevo", "10300-1", "OTHER"),
    ("LEGO 75308 R2-D2 SOLO EN CAJA", "75308-1", "BOX_ONLY"),
    ("LEGO 75308 R2-D2 libro solo", "75308-1", "INSTRUCTIONS"),
    ("LEGO 75308 R2-D2 faltan bolsas y manual", "75308-1", "INCOMPLETE_SET"),
    ("Lego instrucciones de construccion 42115 Lamborghini Sian", "42115-1",
     "INSTRUCTIONS"),
    ("Supporto Muro Lamborghini Sian 42115 compatibile LEGO", "42115-1",
     "ACCESSORY"),
    ("Supporto infuocato per LEGO DeLorean 10300", "10300-1", "ACCESSORY"),
    ("LEGO instrucciones solo para set 21318 Tree House", "21318-1",
     "INSTRUCTIONS"),
    ("LEGO 10300 bolsa #11-B sellada", "10300-1", "PARTS"),
    ("LEGO 10295 Porsche 911 VIP Owners Pack Wallet GWP", "10295-1", "ACCESSORY"),
])
def test_cross_product_contaminants_are_filtered(title, set_num, expected):
    result = classify_ebay_listing(
        {"title": title}, set_num=set_num, expected_terms=()
    )
    assert result.category == expected


def test_ambiguous_numbered_listing_requires_review():
    result = classify_ebay_listing(
        {"title": "Listado 6: LEGO Star Wars 75308 R2-D2"},
        set_num="75308-1",
        expected_terms=("R2-D2",),
    )
    assert result.category == "UNCERTAIN"


@pytest.mark.parametrize("condition,condition_id,expected", [
    ("Nuevo", "1000", "NEW"),
    ("Gebraucht", "3000", "USED"),
    (None, None, "UNKNOWN"),
])
def test_condition_normalization(condition, condition_id, expected):
    assert normalized_condition({
        "condition": condition, "conditionId": condition_id
    }) == expected
