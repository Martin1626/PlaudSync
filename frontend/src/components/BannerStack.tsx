import Banner, { type BannerData } from "./Banner";

interface Props {
  banners: BannerData[];
  onDismiss: (id: string) => void;
  onAction: (banner: BannerData) => void;
}

export default function BannerStack({ banners, onDismiss, onAction }: Props) {
  if (banners.length === 0) return null;
  return (
    <div className="border-b border-gray-200">
      {banners.map((b) => (
        <Banner
          key={b.id}
          banner={b}
          onDismiss={onDismiss}
          onAction={onAction}
        />
      ))}
    </div>
  );
}
