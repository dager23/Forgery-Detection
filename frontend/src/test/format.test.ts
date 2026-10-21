import { bandFor10, formatBytes } from "../format";

describe("format helpers", () => {
  it("maps module scores to the README's flag bands", () => {
    expect(bandFor10(10)).toBe("authentic");
    expect(bandFor10(8)).toBe("authentic");
    expect(bandFor10(7.9)).toBe("suspicious");
    expect(bandFor10(4)).toBe("suspicious");
    expect(bandFor10(3.9)).toBe("tampered");
  });

  it("formats byte sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
