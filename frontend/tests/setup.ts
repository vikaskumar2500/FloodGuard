import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

class EventSourceMock extends EventTarget {
  static instances: EventSourceMock[] = [];
  readonly url: string;
  onerror: ((event: Event) => void) | null = null;
  closed = false;
  constructor(url: string | URL) {
    super();
    this.url = String(url);
    EventSourceMock.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}

Object.defineProperty(globalThis, "EventSource", {
  value: EventSourceMock,
  configurable: true,
});

afterEach(() => {
  cleanup();
  EventSourceMock.instances.length = 0;
});
