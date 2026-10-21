import { render, screen } from "@testing-library/react";
import { ApiError } from "../api";
import { ErrorNote, ScoreGauge, VerdictBadge } from "../components/ui";

describe("UI components", () => {
  it("labels verdicts with the accept / reject wording", () => {
    render(
      <>
        <VerdictBadge verdict="authentic" />
        <VerdictBadge verdict="tampered" />
      </>,
    );
    expect(screen.getByText("Accepted")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });

  it("renders an accessible score gauge", () => {
    render(<ScoreGauge score={37.4} verdict="tampered" />);
    expect(screen.getByRole("img", { name: "Authenticity score 37 of 100" })).toBeInTheDocument();
  });

  it("shows API error messages", () => {
    render(<ErrorNote error={new ApiError(409, "An account with this email already exists")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("already exists");
  });
});
