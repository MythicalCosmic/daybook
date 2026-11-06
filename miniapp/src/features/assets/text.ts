/** The equipment feature's translator. */
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { messages } from "./messages";

export type MineKey = keyof typeof messages.en;
export type MineT = FeatureTranslate<MineKey>;

export const useMineT = (): MineT => useFeatureT(messages);
