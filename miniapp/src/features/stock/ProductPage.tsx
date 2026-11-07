/**
 * One item of the catalogue (PLAN-OWNER §14.17): the price per pack and per part, what is here
 * by batch (series and expiry), what the company's other pharmacies hold, and the items with the
 * same active ingredient, form and strength, the ones in stock first. That list is a catalogue
 * fact for the pharmacist, never advice. With none here: "Add to defektura".
 */
import { Building2, FilePlus2, NotebookPen, PackageX, Pill } from "lucide-react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Banner, Button, Card, ListCard, ListRow, LoadError, PageHeader, Screen, SectionHead } from "../../ui";
import type { PageProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { operatesStock } from "./access";
import { useProduct, useStockSettings, type Analog, type AppBatch, type LookupRow } from "./api";
import { num, qtyText, sortAnalogs } from "./lib";
import { BatchState, ProductBadges, ProductSkeleton, expiryLine, formLine, partWord, useMoney } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

export default function ProductPage({ params }: PageProps) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id) || 0;
  const detail = useProduct(member.companyId, id);
  if (!detail.data) {
    return (
      <Screen variant="detail">
        <PageHeader kicker={t("page.title")} title={t("page.title")} onBack={navigation.pop} />
        {detail.isError ? <LoadError error={detail.error} onRetry={() => void detail.refetch()} onBack={navigation.pop} /> : <ProductSkeleton />}
      </Screen>
    );
  }
  const { product, batches, analogs } = detail.data;
  const subtitle = [product.trade_name, formLine(t, product.dosage_form, product.strength)].filter(Boolean).join(" · ");
  return (
    <Screen variant="detail">
      <PageHeader kicker={t("page.title")} title={product.name} subtitle={subtitle || undefined} onBack={navigation.pop} />
      <ProductBadges rx={product.rx_required} storage={product.storage} control={product.control_class} />
      <PriceCard product={product} />
      <Here product={product} batches={batches} />
      <Elsewhere product={product} />
      <Analogs analogs={analogs} />
    </Screen>
  );
}

function PriceCard({ product }: { product: LookupRow }) {
  const t = useStockT();
  const money = useMoney();
  const parts = product.units_per_pack > 1;
  return (
    <Card className="stk-price-card">
      <div className="stk-price-line">
        <span className="stk-price-label">{t("product.price")}</span>
        <span className="stk-price-value num">{money(product.sale_price)}</span>
      </div>
      {parts && (
        <div className="stk-price-line">
          <span className="stk-price-label">{t("product.partPrice", { label: partWord(t, product.part_label) })}</span>
          <span className="stk-price-value stk-price-value--small num">{money(product.part_price)}</span>
        </div>
      )}
      <p className="ft-hint">
        {parts ? t("product.packOf", { n: product.units_per_pack, label: partWord(t, product.part_label) }) : t("product.wholePacks")}
        {product.inn ? ` · ${t("product.inn", { inn: product.inn })}` : ""}
      </p>
    </Card>
  );
}

function Here({ product, batches }: { product: LookupRow; batches: AppBatch[] }) {
  const t = useStockT();
  const member = useMember();
  const open = useFeatureOpen("stock");
  const settings = useStockSettings(member.companyId);
  const operates = operatesStock(member);
  const held = product.quantity === null ? null : num(product.quantity);
  const rx = operates && product.rx_required && settings.data?.rx_log === true && (
    <Button variant="secondary" block icon={NotebookPen} onClick={() => open.page("rx", { product: product.id })}>
      {t("product.rx")}
    </Button>
  );
  if (held !== null && held <= 0) {
    return (
      <>
        <Banner tone="accent" icon={PackageX} title={t("product.noneHere")} body={t("product.noneHereBody")} />
        {operates && (
          <Button variant="primary" block icon={FilePlus2} onClick={() => open.sheet("defektura", { product: product.id, name: product.name })}>
            {t("hub.defektura")}
          </Button>
        )}
        {rx}
      </>
    );
  }
  return (
    <>
      {held !== null && (
        <SectionHead>
          {t("product.here")}: <span className="num">{qtyText(product.quantity, product.units_per_pack, product.part_label, t)}</span>
        </SectionHead>
      )}
      {batches.length > 0 && (
        <ListCard>
          {batches.map((batch) => (
            <ListRow
              key={batch.id}
              title={
                <span className="stk-batch-title">
                  {t("product.series", { series: batch.series })}
                  <BatchState expired={batch.expired} status={batch.status} />
                </span>
              }
              subtitle={expiryLine(t, batch.expires_on, batch.days_left)}
              alert={batch.expired || batch.days_left <= 30}
              value={qtyText(batch.quantity, product.units_per_pack, product.part_label, t)}
            />
          ))}
        </ListCard>
      )}
      {rx}
    </>
  );
}

function Elsewhere({ product }: { product: LookupRow }) {
  const t = useStockT();
  const places = product.elsewhere.filter((place) => num(place.quantity) > 0);
  if (!places.length) return null;
  return (
    <>
      <SectionHead>{t("product.elsewhere")}</SectionHead>
      <ListCard>
        {places.map((place) => (
          <ListRow key={place.branch_id} icon={Building2} title={place.branch} value={qtyText(place.quantity, product.units_per_pack, product.part_label, t)} />
        ))}
      </ListCard>
    </>
  );
}

function Analogs({ analogs }: { analogs: Analog[] }) {
  const t = useStockT();
  const money = useMoney();
  const open = useFeatureOpen("stock");
  return (
    <section className="stk-analogs" aria-label={t("product.analogs")}>
      <SectionHead>{t("product.analogs")}</SectionHead>
      <p className="ft-hint stk-analogs-note">{t("product.analogsNote")}</p>
      {analogs.length === 0 ? (
        <p className="ft-quiet">{t("product.noAnalogs")}</p>
      ) : (
        <ListCard>
          {sortAnalogs(analogs).map((analog) => {
            const held = num(analog.quantity);
            const about = [analog.trade_name, analog.manufacturer].filter(Boolean).join(" · ");
            return (
              <ListRow
                key={analog.id}
                icon={Pill}
                title={analog.name}
                subtitle={[about, t(held > 0 ? "row.have" : "row.none")].filter(Boolean).join(" · ")}
                value={money(analog.sale_price)}
                onClick={() => open.page("product", { id: analog.id })}
              />
            );
          })}
        </ListCard>
      )}
    </section>
  );
}
