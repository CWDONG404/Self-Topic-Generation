import * as Dialog from '@radix-ui/react-dialog';
import {
  BookOpenText,
  BrainCircuit,
  CircleHelp,
  FileCheck2,
  FilePlus2,
  Home,
  Menu,
  Settings2,
  Sparkles,
  Target,
  X,
} from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { cn } from '../lib/utils';

const navigation = [
  { to: '/', label: '总览', icon: Home, end: true },
  { to: '/knowledge', label: '资料库', icon: BookOpenText },
  { to: '/generate', label: '新建试卷', icon: FilePlus2 },
  { to: '/papers', label: '模拟卷', icon: FileCheck2 },
  { to: '/wrong-answers', label: '错题回看', icon: Target },
  { to: '/settings', label: '模型设置', icon: Settings2 },
];

function Brand() {
  return (
    <NavLink to="/" className="flex items-center gap-3 rounded-xl" aria-label="知题 StudyForge 首页">
      <span className="grid h-10 w-10 place-items-center rounded-xl bg-pine-700 font-display text-lg font-bold text-white shadow-sm">
        知
      </span>
      <span>
        <strong className="block text-base tracking-tight text-ink">知题</strong>
        <span className="block text-[10px] font-bold uppercase tracking-[.16em] text-stone-400">StudyForge</span>
      </span>
    </NavLink>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="主导航" className="space-y-1">
      {navigation.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'group flex min-h-11 items-center gap-3 rounded-xl px-3.5 text-sm font-semibold transition',
              isActive ? 'bg-pine-700 text-white shadow-sm' : 'text-stone-500 hover:bg-stone-100 hover:text-ink',
            )
          }
        >
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

const routeNames: Array<[string, string]> = [
  ['/knowledge', '资料库'],
  ['/generate', '新建试卷'],
  ['/jobs', '生成任务'],
  ['/papers', '模拟卷'],
  ['/practice', '答题'],
  ['/results', '练习结果'],
  ['/wrong-answers', '错题回看'],
  ['/settings', '模型设置'],
];

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const routeName = routeNames.find(([path]) => location.pathname.startsWith(path))?.[1] ?? '总览';

  return (
    <div className="min-h-screen bg-transparent">
      <a
        href="#main-content"
        className="fixed left-3 top-3 z-[100] -translate-y-20 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white transition focus:translate-y-0"
      >
        跳到主要内容
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-stone-200/80 bg-[#FAF8F2]/95 px-5 py-6 backdrop-blur lg:flex lg:flex-col">
        <Brand />
        <div className="mt-9">
          <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[.18em] text-stone-400">知识工作台</p>
          <Navigation />
        </div>
        <div className="mt-auto rounded-2xl border border-pine-100 bg-pine-50 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-pine-900">
            <BrainCircuit aria-hidden="true" className="h-4 w-4" />
            三重质量门
          </div>
          <p className="text-xs leading-5 text-pine-700">考点规划、证据出题、独立审查，每道题都可回到原文。</p>
        </div>
        <a href="/health" className="mt-3 flex items-center gap-2 px-3 py-2 text-xs font-medium text-stone-400 hover:text-stone-600">
          <CircleHelp aria-hidden="true" className="h-3.5 w-3.5" />
          服务状态
        </a>
      </aside>

      <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-stone-200/80 bg-paper/90 px-4 backdrop-blur lg:hidden">
        <Brand />
        <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
          <Dialog.Trigger asChild>
            <button className="grid h-10 w-10 place-items-center rounded-xl border border-stone-200 bg-white" aria-label="打开导航菜单">
              <Menu aria-hidden="true" className="h-5 w-5" />
            </button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-sm" />
            <Dialog.Content className="fixed inset-y-0 right-0 z-50 w-[min(88vw,22rem)] bg-[#FAF8F2] p-5 shadow-drawer focus:outline-none">
              <div className="flex items-center justify-between">
                <Dialog.Title className="text-sm font-semibold text-ink">导航 · {routeName}</Dialog.Title>
                <Dialog.Close className="grid h-10 w-10 place-items-center rounded-xl hover:bg-stone-100" aria-label="关闭导航菜单">
                  <X aria-hidden="true" className="h-5 w-5" />
                </Dialog.Close>
              </div>
              <div className="mt-6"><Navigation onNavigate={() => setMenuOpen(false)} /></div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </header>

      <main id="main-content" className="min-h-screen lg:pl-64">
        <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8 lg:px-10 lg:py-10">
          <Outlet />
        </div>
      </main>

      <NavLink
        to="/generate"
        className="fixed bottom-5 right-5 z-20 flex h-13 items-center gap-2 rounded-full bg-pine-700 px-5 py-3 text-sm font-bold text-white shadow-lg transition hover:bg-pine-900 lg:hidden"
      >
        <Sparkles aria-hidden="true" className="h-4 w-4" />
        新建试卷
      </NavLink>
    </div>
  );
}
