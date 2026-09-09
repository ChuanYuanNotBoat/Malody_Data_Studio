import type {ReactNode} from "react";
import {Typography} from "antd";

type PageFrameProps = {
  title: string;
  description?: string;
  children: ReactNode;
};

export function PageFrame({title, description, children}: PageFrameProps) {
  return (
    <div className="page-frame">
      <div className="page-heading">
        <Typography.Title level={2}>{title}</Typography.Title>
        {description ? <Typography.Text type="secondary">{description}</Typography.Text> : null}
      </div>
      {children}
    </div>
  );
}
