import type { ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { buttonClasses, type ButtonSize, type ButtonVariant } from "./buttonStyles";

/** A navigation link styled as a button (never a <button> inside an <a>). */
export function LinkButton({
  variant = "primary",
  size = "md",
  icon,
  className = "",
  children,
  ...rest
}: LinkProps & { variant?: ButtonVariant; size?: ButtonSize; icon?: ReactNode }) {
  return (
    <Link className={buttonClasses(variant, size, className)} {...rest}>
      {icon}
      {children}
    </Link>
  );
}
