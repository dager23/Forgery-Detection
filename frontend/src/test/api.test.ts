import { afterEach, vi } from "vitest";
import { ApiError, request, setUnauthorizedHandler } from "../api";

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

describe("api.request", () => {
  it("surfaces FastAPI detail strings", async () => {
    mockFetch(409, { detail: "An account with this email already exists" });
    await expect(request("/api/auth/register")).rejects.toMatchObject({
      status: 409,
      message: "An account with this email already exists",
    });
  });

  it("flattens validation errors into readable text", async () => {
    mockFetch(422, {
      detail: [{ loc: ["body", "password"], msg: "Value error, Password must be at least 8 characters" }],
    });
    await expect(request("/api/auth/register")).rejects.toThrow("password: Password must be at least 8 characters");
  });

  it("reports an unreachable server", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const err = (await request("/api/health").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });

  it("signals an expired session on 401 outside auth routes", async () => {
    const onExpired = vi.fn();
    setUnauthorizedHandler(onExpired);
    mockFetch(401, { detail: "Not authenticated" });
    await expect(request("/api/analyses")).rejects.toBeInstanceOf(ApiError);
    expect(onExpired).toHaveBeenCalledOnce();
    mockFetch(401, { detail: "Incorrect email or password" });
    await expect(request("/api/auth/login")).rejects.toBeInstanceOf(ApiError);
    expect(onExpired).toHaveBeenCalledOnce();
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(204, undefined);
    await expect(request("/api/analyses/x")).resolves.toBeUndefined();
  });
});
