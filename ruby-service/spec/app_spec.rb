# frozen_string_literal: true

require 'spec_helper'
require 'rack/test'
require 'json'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'aggregates service health statuses' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .and_return({ status: 'healthy' }, { status: 'unreachable', error: 'timeout' })

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']).to include('ruby', 'go', 'python')
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('unreachable')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review for valid inputs' do
      diff_result = { 'changes' => [{ 'line' => 1, 'type' => 'add' }], 'summary' => '1 addition' }
      review_result = { 'score' => 75.5, 'issues' => [] }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(:old_content, :new_content)).and_return(diff_result)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content)).and_return(review_result)

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to eq(diff_result)
      expect(json_response['new_code_review']).to eq(review_result)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and overall_quality' do
      metrics = { 'complexity' => 2 }
      review = { 'score' => 90, 'issues' => [{}] } # base 0.9, penalties 0.2 + 0.5 => 20.0
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(:content)).and_return(metrics)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content)).and_return(review)

      post '/metrics', { content: 'def x(): pass' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['metrics']).to eq(metrics)
      expect(json_response['review']).to eq(review)
      expect(json_response['overall_quality']).to eq(20.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end

    it 'returns aggregated dashboard statistics and summary' do
      files = [{ 'path' => 'lib/a.rb', 'content' => 'puts :ok' }]
      file_stats = {
        'total_files' => 4,
        'total_lines' => 100,
        'languages' => { 'ruby' => 4 }
      }
      review_stats = {
        'average_score' => 80.0,
        'total_issues' => 2,
        'average_complexity' => 0.1
      }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(:files)).and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(:files)).and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['file_statistics']).to eq(file_stats)
      expect(json_response['review_statistics']).to eq(review_stats)
      expect(json_response['summary']['total_files']).to eq(4)
      expect(json_response['summary']['total_lines']).to eq(100)
      expect(json_response['summary']['languages']).to eq({ 'ruby' => 4 })
      expect(json_response['summary']['average_quality_score']).to eq(80.0)
      expect(json_response['summary']['total_issues']).to eq(2)
      expect(json_response['summary']['health_score']).to eq(76.0)
    end
  end

  describe 'private utilities' do
    let(:instance) { app.new }

    describe '#detect_language' do
      it 'detects known languages from file extensions' do
        expect(instance.send(:detect_language, 'main.go')).to eq('go')
        expect(instance.send(:detect_language, 'script.py')).to eq('python')
        expect(instance.send(:detect_language, 'app.rb')).to eq('ruby')
        expect(instance.send(:detect_language, 'index.js')).to eq('javascript')
        expect(instance.send(:detect_language, 'types.ts')).to eq('typescript')
        expect(instance.send(:detect_language, 'App.java')).to eq('java')
      end

      it 'returns unknown for unsupported extensions' do
        expect(instance.send(:detect_language, 'README.txt')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'calculates a positive score with penalties applied' do
        metrics = { 'complexity' => 2 }
        review = { 'score' => 90, 'issues' => [{}] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(20.0)
      end

      it 'clamps the score to 100 maximum' do
        metrics = { 'complexity' => 0 }
        review = { 'score' => 150, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(100)
      end

      it 'returns 0.0 when metrics or review contain errors' do
        metrics = { 'error' => 'failed' }
        review = { 'score' => 90, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(0.0)

        metrics_ok = { 'complexity' => 1 }
        review_err = { 'error' => 'failed' }
        expect(instance.send(:calculate_quality_score, metrics_ok, review_err)).to eq(0.0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'computes health score using issues and complexity penalties' do
        file_stats = { 'total_files' => 4 }
        review_stats = { 'average_score' => 80.0, 'total_issues' => 2, 'average_complexity' => 0.1 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(76.0)
      end

      it 'clamps health score to a minimum of 0' do
        file_stats = { 'total_files' => 1 }
        review_stats = { 'average_score' => 10.0, 'total_issues' => 100, 'average_complexity' => 2.0 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(0.0)
      end

      it 'clamps health score to a maximum of 100' do
        file_stats = { 'total_files' => 1 }
        review_stats = { 'average_score' => 150.0, 'total_issues' => 0, 'average_complexity' => 0.0 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(100.0)
      end

      it 'returns 0.0 when stats contain errors' do
        file_stats = { 'error' => 'down' }
        review_stats = { 'average_score' => 80.0 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(0.0)

        file_stats_ok = { 'total_files' => 2 }
        review_stats_err = { 'error' => 'down' }
        expect(instance.send(:calculate_dashboard_health_score, file_stats_ok, review_stats_err)).to eq(0.0)
      end
    end

    describe '#check_service_health' do
      it 'returns healthy when service responds 200' do
        allow(HTTParty).to receive(:get).with('http://x/health', timeout: 2).and_return(double(code: 200))
        expect(instance.send(:check_service_health, 'http://x')).to eq({ status: 'healthy' })
      end

      it 'returns unhealthy when service responds non-200' do
        allow(HTTParty).to receive(:get).with('http://x/health', timeout: 2).and_return(double(code: 500))
        expect(instance.send(:check_service_health, 'http://x')).to eq({ status: 'unhealthy' })
      end

      it 'returns unreachable on exceptions' do
        allow(HTTParty).to receive(:get).with('http://x/health', timeout: 2).and_raise(StandardError.new('boom'))
        result = instance.send(:check_service_health, 'http://x')
        expect(result[:status]).to eq('unreachable')
        expect(result[:error]).to include('boom')
      end
    end
  end
end
