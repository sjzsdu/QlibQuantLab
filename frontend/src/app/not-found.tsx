import Link from "next/link";
import { Button, Result } from "antd";

/** 404 页面（中文） */
export default function NotFound() {
  return (
    <Result
      status="404"
      title="404"
      subTitle="抱歉，你访问的页面不存在或已被移除。"
      extra={
        <Link href="/">
          <Button type="primary">返回首页</Button>
        </Link>
      }
    />
  );
}
