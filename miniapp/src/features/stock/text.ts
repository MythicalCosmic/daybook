/** The stock feature's translator. */
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { messages } from "./messages";

export type StockKey = keyof typeof messages.en;
export type StockT = FeatureTranslate<StockKey>;

export const useStockT = (): StockT => useFeatureT(messages);
