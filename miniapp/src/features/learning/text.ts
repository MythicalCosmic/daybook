/** The learning feature's translator. */
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { messages } from "./messages";

export type LearningKey = keyof typeof messages.en;
export type LearningT = FeatureTranslate<LearningKey>;

export const useLearningT = (): LearningT => useFeatureT(messages);
