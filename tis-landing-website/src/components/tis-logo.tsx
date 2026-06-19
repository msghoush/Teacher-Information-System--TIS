import Image from "next/image";

type TisLogoProps = {
  theme?: "light" | "dark";
  layout?: "horizontal" | "stacked";
  responsive?: boolean;
  className?: string;
  alt?: string;
  priority?: boolean;
};

const dash = "\u2013";
const logoRoot =
  process.env.NEXT_PUBLIC_TIS_ASSET_BASE_URL ??
  "https://app.tisplatform.com/static/branding/tis/logos";

function logoPath(
  theme: "light" | "dark",
  layout: "horizontal" | "stacked",
  compact = false
) {
  let filename: string;
  if (compact) {
    filename = `TIS Wordmark Only ${dash} ${theme === "dark" ? "White" : "Dark Blue"}.png`;
  } else {
    const palette = theme === "dark" ? "White & Light Orange" : "Full Color";
    const arrangement = layout === "stacked" ? "Stacked" : "Horizontal";
    filename = `TIS Logo ${dash} ${palette} ${dash} ${arrangement} Layout.png`;
  }
  return `${logoRoot}/${filename}`;
}

export function TisLogo({
  theme = "light",
  layout = "horizontal",
  responsive = true,
  className = "",
  alt = "TIS Platform",
  priority = false
}: TisLogoProps) {
  return (
    <span
      className={`tis-logo-set tis-logo-set--${layout} ${
        responsive ? "tis-logo-set--responsive" : ""
      } ${className}`.trim()}
    >
      <span className={`tis-logo-crop tis-logo-crop--${layout}`}>
        <Image
          src={logoPath(theme, layout)}
          alt={alt}
          width={1563}
          height={1563}
          unoptimized
          priority={priority}
        />
      </span>
      {responsive ? (
        <span className="tis-logo-crop tis-logo-crop--wordmark" aria-hidden="true">
          <Image
            src={logoPath(theme, layout, true)}
            alt=""
            width={1563}
            height={1563}
            unoptimized
          />
        </span>
      ) : null}
    </span>
  );
}
