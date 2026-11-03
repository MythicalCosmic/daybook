/** Opening a feature's own pages and sheets, with the selection tick every opening gets. */
import { useNavigation, type Params } from "../state/navigation";
import { haptic } from "../telegram";

export function useFeatureOpen(feature: string) {
  const navigation = useNavigation();
  return {
    page: (page: string, params?: Params) => {
      haptic.select();
      navigation.push({ feature, page, params });
    },
    sheet: (sheet: string, params?: Params) => {
      haptic.select();
      navigation.openSheet({ kind: "feature", feature, sheet, params });
    },
  };
}
