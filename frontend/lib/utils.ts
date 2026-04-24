import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type FastApiValidationItem = {
  msg?: string;
  loc?: Array<string | number>;
};

export function getApiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;

  if (!detail) return fallback;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;

        const validation = item as FastApiValidationItem;
        if (validation?.msg) {
          const field = Array.isArray(validation.loc)
            ? validation.loc.filter((part) => part !== "body").join(".")
            : "";
          return field ? `${field}: ${validation.msg}` : validation.msg;
        }

        return "";
      })
      .filter(Boolean);

    if (messages.length > 0) {
      return messages.join(" | ");
    }
  }

  if (typeof detail === "object") {
    const maybeMsg = (detail as { msg?: string }).msg;
    if (maybeMsg) return maybeMsg;
  }

  return fallback;
}
