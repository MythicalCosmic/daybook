"""The catalogue import: what a cell says about prescriptions, control and storage is read or
refused, never guessed, and an empty cell leaves the item as it is."""

import io

import pytest

from apps.core.exceptions import DomainError
from apps.inventory import importing
from apps.inventory.models import Product
from apps.inventory.tests.factories import ProductFactory

pytestmark = pytest.mark.django_db

HEADER = "name;barcode;rx_required;control_class;storage;dosage_form;kind"


def upload(*rows: str):
    data = io.BytesIO(("\n".join([HEADER, *rows]) + "\n").encode())
    data.name = "catalogue.csv"
    return data


def run(shop, owner, *rows: str, dry_run: bool = False) -> dict:
    return importing.import_products(shop, upload(*rows), by=owner, dry_run=dry_run)


def test_new_items_read_codes_names_and_yes_or_no(shop, owner):
    result = run(
        shop,
        owner,
        "Tramadol 50 mg №10;4780000000101;да;psychotropic;cold;capsule;dori",
        "Analgin 500 mg №10;4780000000102;нет;;;;",
        "Vitamin C;4780000000103;;Not controlled;Fridge, 2–8 °C;Tablet;бад",
    )
    assert (result["created"], result["skipped"]) == (3, 0), result["rows"]
    tramadol = Product.objects.get(barcode="4780000000101")
    assert tramadol.rx_required and tramadol.control_class == "psychotropic"
    assert (tramadol.storage, tramadol.dosage_form, tramadol.kind) == (
        "cold",
        "capsule",
        "medicine",
    )
    analgin = Product.objects.get(barcode="4780000000102")
    assert not analgin.rx_required
    assert (analgin.control_class, analgin.storage) == ("none", "room")
    # A choice is also read by the name the app shows for it.
    vitamin = Product.objects.get(barcode="4780000000103")
    assert (vitamin.control_class, vitamin.storage, vitamin.dosage_form, vitamin.kind) == (
        "none",
        "cold",
        "tablet",
        "supplement",
    )


def test_a_word_it_cannot_read_skips_the_row_and_changes_nothing(shop, owner):
    """Before, an unknown word was quietly read as "no": a psychotropic kept cold and sold on
    prescription came out of an update uncontrolled, at room temperature and over the counter."""
    product = ProductFactory(
        company=shop,
        name="Tramadol 50 mg №10",
        barcode="4780000000101",
        rx_required=True,
        control_class=Product.ControlClass.PSYCHOTROPIC,
        storage=Product.Storage.COLD,
        dosage_form=Product.DosageForm.CAPSULE,
    )
    result = run(
        shop,
        owner,
        "Tramadol 50 mg №10;4780000000101;по рецепту;психотропное;холодильник;капсулы;лс",
    )
    assert (result["updated"], result["skipped"]) == (0, 1)
    [row] = result["rows"]
    assert row["action"] == "skip" and len(row["errors"]) == 3  # yes/no, control, storage
    product.refresh_from_db()
    assert product.rx_required and product.control_class == "psychotropic"
    assert product.storage == "cold" and product.dosage_form == "capsule"


def test_an_empty_cell_leaves_the_item_as_it_is(shop, owner):
    product = ProductFactory(
        company=shop,
        name="Tramadol 50 mg №10",
        barcode="4780000000101",
        rx_required=True,
        control_class=Product.ControlClass.PSYCHOTROPIC,
        storage=Product.Storage.COLD,
        dosage_form=Product.DosageForm.CAPSULE,
        kind=Product.Kind.MEDICINE,
    )
    # Only the name changes; a dosage form it doesn't know is left alone as well.
    result = run(shop, owner, "Tramadol 50 mg kapsula №10;4780000000101;;;;kapsulalar;")
    assert (result["updated"], result["skipped"]) == (1, 0), result["rows"]
    product.refresh_from_db()
    assert product.name == "Tramadol 50 mg kapsula №10"
    assert product.rx_required and product.control_class == "psychotropic"
    assert product.storage == "cold" and product.dosage_form == "capsule"
    # Said in so many words, it does change.
    run(shop, owner, "Tramadol 50 mg kapsula №10;4780000000101;no;none;room;;")
    product.refresh_from_db()
    assert not product.rx_required
    assert (product.control_class, product.storage) == ("none", "room")


def test_a_list_of_names_and_a_broken_workbook_are_no_server_errors(shop, owner):
    """One column gives the reader no separator to find, and a file that only looks like a
    workbook can't be opened: the first is read, the second refused in words (both used to be
    an unhandled error)."""
    names = io.BytesIO("name\nParatsetamol 500 mg №20\nAnalgin 500 mg №10\n".encode())
    names.name = "names.csv"
    result = importing.import_products(shop, names, by=owner, dry_run=True)
    assert (result["created"], result["skipped"]) == (2, 0)

    broken = io.BytesIO(b"PK\x03\x04 this is no workbook")
    broken.name = "catalogue.xlsx"
    with pytest.raises(DomainError):
        importing.import_products(shop, broken, by=owner, dry_run=True)
