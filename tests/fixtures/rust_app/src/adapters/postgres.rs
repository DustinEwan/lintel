use crate::app::run;
use sqlx::PgPool;

pub fn execute(pool: &PgPool) {
    let _ = pool;
    run(crate::domain::order::Order);
}
