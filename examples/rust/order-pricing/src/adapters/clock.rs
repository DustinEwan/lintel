use std::time::SystemTime;

use crate::core::ports::ClockPort;

pub struct SystemClock;

impl ClockPort for SystemClock {
    fn now(&self) -> SystemTime {
        SystemTime::now()
    }
}

pub struct FixedClock {
    value: SystemTime,
}

impl FixedClock {
    pub fn new(value: SystemTime) -> Self {
        Self { value }
    }
}

impl ClockPort for FixedClock {
    fn now(&self) -> SystemTime {
        self.value
    }
}
