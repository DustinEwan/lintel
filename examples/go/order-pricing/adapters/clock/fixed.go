package clock

import "time"

type FixedClock struct {
	value time.Time
}

func NewFixedClock(value time.Time) FixedClock {
	return FixedClock{value: value}
}

func (c FixedClock) Now() time.Time {
	return c.value
}
