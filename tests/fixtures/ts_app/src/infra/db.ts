import { order } from "../domain/order";

export function connect() {
  return order();
}

const loadWithAttributes = () =>
  import("../domain/order", { with: { type: "json" } });
