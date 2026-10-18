import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';

const GITHUB_URL = 'https://github.com/sjzsdu/QlibQuantLab';

type Card = {
  icon: string;
  title: string;
  body: string;
  to: string;
  meta: string;
};

const capabilities: Card[] = [
  {
    icon: '01',
    title: '研究资产：项目 · 数据 · 因子',
    body: '项目按可见性隔离研究内容；数据入库前先登记来源与授权台账；因子表达式落库前做静态校验，改动即版本 +1。',
    to: '/features',
    meta: 'projects · data · factors',
  },
  {
    icon: '02',
    title: '计算：训练 · 回测 · 任务中心',
    body: '因子快照进模型，训练与回测统一提交为后台任务，状态、日志、取消与重试都在任务中心可见。',
    to: '/features',
    meta: 'models · backtests · jobs',
  },
  {
    icon: '03',
    title: '治理：多租户 · RBAC · 审计',
    body: '15 张业务表强制 org_id 隔离；四种角色按权限矩阵授权；写入、导出、删除全量留痕，可按 request_id 串联。',
    to: '/features',
    meta: 'orgs · rbac · audit',
  },
];

function Terminal(): ReactNode {
  return (
    <div className="qql-terminal">
      <div className="qql-terminal__bar">
        <span />
        <span />
        <span />
        <span className="qql-terminal__title">模式 A · 自包含</span>
      </div>
      <pre>
        <code>
          <span className="qql-comment"># 前置：Docker + Compose v2</span>
          {'\n'}
          <span className="qql-cmd">cp</span> .env.example .env{'\n'}
          <span className="qql-cmd">docker compose up</span> -d --build{'\n'}
          <span className="qql-cmd">curl</span> -s localhost:8000/api/v1/health/ready{'\n\n'}
          <span className="qql-comment"># backend=healthy · migrate=exited(0)</span>
          {'\n'}
          <span className="qql-comment"># 打开 http://localhost:3000/login</span>
        </code>
      </pre>
    </div>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={siteConfig.tagline}
      description="QlibQuantLab 是基于 Qlib 的开源多用户量化研究平台：多组织数据与策略隔离、可插拔认证、审计留痕，训练与回测在独立 worker 容器执行。仅供研究、教学与技术验证使用，不构成投资建议。">
      <header className="qql-hero">
        <div className="qql-container qql-hero__inner">
          <div>
            <p className="qql-hero__badge">
              <span className="qql-hero__dot" />
              0.1.0 · 阶段 1–6 已交付 · 401 项后端测试通过
            </p>
            <h1 className="qql-hero__title">
              基于 Qlib 的<em>多用户</em>
              <br />
              量化研究平台
            </h1>
            <p className="qql-hero__sub">
              多组织数据与策略隔离、可插拔认证、全链路审计留痕。训练与回测跑在独立 worker
              容器里，Web 进程永不 <code>import qlib</code> —— 让研究过程可复现、可追溯。
            </p>
            <div className="qql-actions">
              <Link className="qql-btn qql-btn--primary" to="/docs/quickstart">
                快速开始 →
              </Link>
              <Link className="qql-btn qql-btn--ghost" to="/architecture">
                看架构与边界
              </Link>
              <Link className="qql-btn qql-btn--ghost" href={GITHUB_URL}>
                GitHub
              </Link>
            </div>
          </div>
          <div>
            <Terminal />
            <figure className="qql-shot" style={{marginTop: '1.5rem'}}>
              <img
                src="/img/screens/home.webp"
                alt="QlibQuantLab 登录后的工作台：入口卡片、风险提示与免责声明"
                width={1440}
                height={900}
                loading="lazy"
              />
              <figcaption>登录后的工作台（演示数据 × Mock 认证）</figcaption>
            </figure>
          </div>
        </div>
      </header>

      <section className="qql-section">
        <div className="qql-container">
          <span className="qql-eyebrow">不是又一个回测框架</span>
          <h2 className="qql-h2">三条与「直接用 Qlib」不同的边界</h2>
          <p className="qql-lead">
            Qlib 解决了从数据到模型的算法链路；QlibQuantLab 解决的是它之外的那部分 ——
            多个团队、多个组织共用同一套研究基础设施时，隔离、权限与可追溯怎么落地。
          </p>
          <ul className="qql-facts" style={{marginTop: '1.75rem'}}>
            <li className="qql-fact">
              <strong>org_id</strong>
              <span>业务表强制组织隔离，跨组织读改删一律 404（不泄露存在性）</span>
            </li>
            <li className="qql-fact">
              <strong>worker only</strong>
              <span>qlib 只出现在 worker 进程，API 镜像物理不含它，架构测试强制执行</span>
            </li>
            <li className="qql-fact">
              <strong>env swap</strong>
              <span>换 IdP（Mock → Casdoor）只改环境变量，前后端代码零改动</span>
            </li>
          </ul>
        </div>
      </section>

      <section className="qql-section qql-section--surface">
        <div className="qql-container">
          <span className="qql-eyebrow">能力</span>
          <h2 className="qql-h2">三组能力，覆盖一次研究的完整闭环</h2>
          <p className="qql-lead">
            从登记数据授权，到因子、训练、回测、导出与审计，全流程在同一个平台上留下可核对的记录。
          </p>
          <div className="qql-grid qql-grid--3" style={{marginTop: '1.75rem'}}>
            {capabilities.map((c) => (
              <Link key={c.title} className="qql-card" to={c.to} style={{color: 'inherit'}}>
                <div className="qql-card__icon">{c.icon}</div>
                <h3>{c.title}</h3>
                <p>{c.body}</p>
                <span className="qql-card__meta">{c.meta}</span>
              </Link>
            ))}
          </div>
          <div className="qql-actions" style={{marginTop: '1.75rem'}}>
            <Link className="qql-btn qql-btn--ghost" to="/features">
              完整能力清单 →
            </Link>
          </div>
        </div>
      </section>

      <section className="qql-section">
        <div className="qql-container">
          <span className="qql-eyebrow">真实界面</span>
          <h2 className="qql-h2">看到的即部署出来的</h2>
          <p className="qql-lead">
            下面两张图来自本机跑着的模式 A 部署栈，数据是演示项目与演示因子，不含任何真实研究内容。
          </p>
          <div className="qql-grid qql-grid--2" style={{marginTop: '1.75rem'}}>
            <figure className="qql-shot">
              <img
                src="/img/screens/projects.webp"
                alt="项目列表页：两个演示项目的可见性与成员信息"
                width={1440}
                height={900}
                loading="lazy"
              />
              <figcaption>项目：可见性、成员与更新时间为一次研究划定边界</figcaption>
            </figure>
            <figure className="qql-shot">
              <img
                src="/img/screens/factors.webp"
                alt="因子库列表页：因子表达式与版本号"
                width={1440}
                height={900}
                loading="lazy"
              />
              <figcaption>因子：表达式落库前静态校验，变更即版本 +1</figcaption>
            </figure>
          </div>
        </div>
      </section>

      <section className="qql-section qql-section--surface">
        <div className="qql-container">
          <span className="qql-eyebrow">成熟度</span>
          <h2 className="qql-h2">现在能做什么，还不能做什么</h2>
          <div className="qql-grid qql-grid--2" style={{marginTop: '1.5rem'}}>
            <div className="qql-card">
              <h3>已经可用</h3>
              <p>
                项目 / 数据 / 因子 / 模型 / 回测 / 任务中心 / 审计 / 合规页八条主链路，模式 A
                一键起栈；后端 401 项测试、Playwright e2e 与实机冒烟均在 CI 与本地可复跑。
              </p>
            </div>
            <div className="qql-card">
              <h3>尚未完成</h3>
              <p>
                0.1.0，<strong>尚未生产就绪</strong>。认证仍是 4 个可切换 profile 的 Mock
                实现（Casdoor 接入是阶段 7），因此<strong>不提供公开在线 demo</strong>
                —— 用截图代替。
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="qql-section qql-section--tight">
        <div className="qql-container" style={{textAlign: 'center'}}>
          <h2 className="qql-h2">在自己的机器上跑一遍</h2>
          <p className="qql-lead" style={{margin: '0 auto 1.5rem'}}>
            只需要 Docker 与 Compose v2。五步之内看到登录页，文档里附了常见报错的排查表。
          </p>
          <div className="qql-actions" style={{justifyContent: 'center'}}>
            <Link className="qql-btn qql-btn--primary" to="/docs/quickstart">
              开始部署 →
            </Link>
            <Link className="qql-btn qql-btn--ghost" to="/legal/disclaimer">
              先读免责声明
            </Link>
          </div>
        </div>
      </section>
    </Layout>
  );
}
