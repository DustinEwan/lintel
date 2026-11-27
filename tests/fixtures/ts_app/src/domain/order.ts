import { connect } from "../infra/db";

export function order() {
  return connect();
}
