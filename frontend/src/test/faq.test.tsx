import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { FaqPage } from "../pages/FaqPage";

describe("FAQ", () => {
  it("searches across questions and answers, accent-insensitively", () => {
    render(
      <MemoryRouter>
        <FaqPage />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/Busca/), { target: { value: "cambio IP" } });
    expect(screen.getByText("¿Cómo cambio la IP de una fuente?")).toBeInTheDocument();
    expect(screen.queryByText("¿Puedo obtener el informe en PDF?")).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Busca/), { target: { value: "contrasena" } });
    expect(screen.getByText("¿Qué hago si una fuente requiere usuario y contraseña?")).toBeInTheDocument();
  });

  it("filters by category and explains an empty result", () => {
    render(
      <MemoryRouter>
        <FaqPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cuenta y seguridad" }));
    expect(screen.queryByText("¿Cómo genero un reporte?")).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Busca/), { target: { value: "zzzz" } });
    expect(screen.getByText("No encontramos esa pregunta")).toBeInTheDocument();
  });
});
