import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';

export default function NotFound(): ReactNode {
  return (
    <Layout title="404 · 页面不存在" description="这个地址没有对应的页面。">
      <main className="qql-section">
        <div className="qql-container" style={{maxWidth: '46rem', textAlign: 'center'}}>
          <p className="qql-eyebrow">404</p>
          <h1 className="qql-h2">这个地址没有对应的页面</h1>
          <p className="qql-lead" style={{margin: '0 auto 1.75rem'}}>
            可能是文档还在写，也可能是链接过期了。下面几个入口通常能带你到想去的地方。
          </p>
          <div className="qql-actions" style={{justifyContent: 'center'}}>
            <Link className="qql-btn qql-btn--primary" to="/">
              回首页
            </Link>
            <Link className="qql-btn qql-btn--ghost" to="/docs/quickstart">
              5 分钟跑起来
            </Link>
            <Link className="qql-btn qql-btn--ghost" to="/features">
              能力清单
            </Link>
          </div>
          <p style={{marginTop: '2rem', fontSize: '0.85rem', color: 'var(--qql-slate)'}}>
            如果这是一个本该存在的页面，请在 GitHub 上开一个 issue —— 站点的外部链接在构建时会做校验，
            站内文档链接写错会让构建直接失败。
          </p>
        </div>
      </main>
    </Layout>
  );
}
