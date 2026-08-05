import { useEffect } from "react";

import { formatDocumentTitle, productName } from "../config/brand";

export function useDocumentTitle(title?: string | null) {
  useEffect(() => {
    document.title = formatDocumentTitle(title);
    return () => {
      document.title = productName;
    };
  }, [title]);
}
