import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch } from "wouter";
import { lazy, Suspense } from "react";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import Home from "./pages/Home";
import { LegalPage } from "./pages/Legal";

const CompiledWorld = lazy(() => import("./pages/CompiledWorld"));
const SecCinematicDemo = lazy(() => import("./pages/SecCinematicDemo"));

function RouteLoader() {
  return <div className="min-h-screen grid place-items-center bg-[#142016] text-[#c7f27a] font-mono text-xs tracking-[0.12em]">LOADING COMPILED WORLD</div>;
}

function Router() {
  // make sure to consider if you need authentication for certain routes
  return (
    <Switch>
      <Route path={"/"} component={Home} />
      <Route path={"/privacy"} component={() => <LegalPage document="privacy" />} />
      <Route path={"/terms"} component={() => <LegalPage document="terms" />} />
      <Route path={"/world"} component={() => <Suspense fallback={<RouteLoader />}><CompiledWorld /></Suspense>} />
      <Route path={"/demo/sec"} component={() => <Suspense fallback={<RouteLoader />}><SecCinematicDemo /></Suspense>} />
      <Route path={"/404"} component={NotFound} />
      {/* Final fallback route */}
      <Route component={NotFound} />
    </Switch>
  );
}

// NOTE: About Theme
// - First choose a default theme according to your design style (dark or light bg), than change color palette in index.css
//   to keep consistent foreground/background color across components
// - If you want to make theme switchable, pass `switchable` ThemeProvider and use `useTheme` hook

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider
        defaultTheme="light"
        // switchable
      >
        <TooltipProvider>
          <Toaster />
          <Router />
        </TooltipProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
